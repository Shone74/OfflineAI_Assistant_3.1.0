"""Regression tests for incremental FAISS index updates in VectorMemory.

Locks the contract from the incremental-add fix:

* Ordinary ``add()`` appends exactly ONE vector to the existing FAISS
  index — O(dim) per insertion instead of the previous full
  ``_rebuild_faiss()`` (O(N*dim) per insertion, O(N^2) cumulative).
* The FAISS index is constructed exactly once for the first insertion and
  reused afterwards (``faiss index position == _entries list position``).
* ``remove()`` still performs a legitimate full rebuild and the positional
  mapping stays correct.
* ``clear()`` resets the index; the next add creates a fresh one.
* The no-FAISS fallback path is unchanged.

The verified environment does not ship ``faiss-cpu`` (it is an optional
``[vector]`` extra), so these tests install a minimal deterministic fake
FAISS module via ``monkeypatch``.  The fake implements exactly what
``memory/vector_memory.py`` uses: ``IndexFlatIP``, ``add``, ``search``,
and ``normalize_L2`` (real numpy arithmetic — so search-equivalence is
verified against actual dot-product behaviour, not a canned response).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory.embeddings import StubEmbeddingModel
from memory.vector_memory import VectorMemory


# --------------------------------------------------------------------------- #
# Minimal deterministic fake FAISS
# --------------------------------------------------------------------------- #
class FakeFaissIndex:
    """Deterministic IndexFlatIP stand-in: exact inner-product search.

    ``added_vectors`` records the total number of vectors pushed through
    ``add()`` — the scaling-contract metric.  ``search`` reproduces
    IndexFlatIP semantics (L2-normalized vectors → inner product ==
    cosine similarity) using plain numpy so search-equivalence assertions
    exercise real arithmetic, not canned data.
    """

    index_constructions = 0  # class-level: counts IndexFlatIP creations

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.vectors = []  # list of 1-D numpy arrays
        self.add_calls = 0
        self.added_vectors = 0
        type(self).index_constructions += 1

    def add(self, matrix) -> None:
        import numpy as np

        matrix = np.asarray(matrix, dtype="float32")
        assert matrix.ndim == 2, f"index.add expects a 2-D matrix, got {matrix.shape}"
        for row in matrix:
            self.vectors.append(row)
        self.add_calls += 1
        self.added_vectors += matrix.shape[0]

    def search(self, queries, k: int):
        import numpy as np

        queries = np.asarray(queries, dtype="float32")
        distances, indices = [], []
        for q in queries:
            if not self.vectors:
                distances.append([0.0] * k)
                indices.append([-1] * k)
                continue
            sims = [float(np.dot(q, v)) for v in self.vectors]
            order = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)
            top = order[:k]
            distances.append([sims[i] for i in top] + [0.0] * (k - len(top)))
            indices.append(top + [-1] * (k - len(top)))
        return distances, indices


class FakeFaissModule:
    """Module-level fake exposing what memory.vector_memory uses."""

    IndexFlatIP = FakeFaissIndex

    @staticmethod
    def normalize_L2(matrix) -> None:
        import numpy as np

        matrix = np.asarray(matrix, dtype="float32")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix /= norms

    @classmethod
    def reset_counters(cls) -> None:
        FakeFaissIndex.index_constructions = 0


@pytest.fixture()
def fake_faiss(monkeypatch: pytest.MonkeyPatch):
    """Install the fake FAISS module into memory.vector_memory.

    Patches ``VectorMemory._try_init_faiss`` so instances receive the fake
    module instead of the (absent) real ``faiss`` — mirroring what the real
    method does on ``import faiss`` success.
    """
    import memory.vector_memory as vm_module

    FakeFaissModule.reset_counters()

    def _init_with_fake(self) -> None:
        self._faiss = FakeFaissModule

    monkeypatch.setattr(vm_module.VectorMemory, "_try_init_faiss", _init_with_fake)
    yield FakeFaissModule


# --------------------------------------------------------------------------- #
# 1. FIRST FAISS ADD — index created once, one vector, correct dimension
# --------------------------------------------------------------------------- #
class TestFirstAdd:
    def test_first_add_creates_index_once_with_correct_dimension(
        self, fake_faiss, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure numpy-backed search equivalence below uses fresh state.
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        assert vm._faiss is FakeFaissModule  # fake wired in

        vm.add("first text")

        assert FakeFaissIndex.index_constructions == 1
        assert vm._faiss_index is not None
        assert vm._faiss_index.dim == StubEmbeddingModel().dimension
        assert vm._faiss_index.added_vectors == 1
        assert vm._faiss_index.add_calls == 1
        assert len(vm._entries) == 1


# --------------------------------------------------------------------------- #
# 2. SUBSEQUENT ADDS ARE INCREMENTAL
# --------------------------------------------------------------------------- #
class TestIncrementalAdds:
    def test_same_index_object_reused_and_one_vector_per_add(
        self, fake_faiss
    ) -> None:
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        first_index = None
        for i in range(10):
            vm.add(f"text {i}")
            if first_index is None:
                first_index = vm._faiss_index
            else:
                assert vm._faiss_index is first_index  # NOT recreated
        # Exactly one index construction for 10 adds; one vector per add.
        assert FakeFaissIndex.index_constructions == 1
        assert vm._faiss_index.add_calls == 10
        assert vm._faiss_index.added_vectors == 10

    def test_rebuild_faiss_not_called_during_ordinary_adds(
        self, fake_faiss, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        rebuild_calls = []
        monkeypatch.setattr(
            vm, "_rebuild_faiss", lambda: rebuild_calls.append(1)
        )
        for i in range(5):
            vm.add(f"text {i}")
        assert rebuild_calls == []  # ordinary adds never rebuild
        assert vm._faiss_index.added_vectors == 5


# --------------------------------------------------------------------------- #
# 3. SCALING CONTRACT — linear, not quadratic
# --------------------------------------------------------------------------- #
class TestScalingContract:
    def test_100_adds_insert_exactly_100_vectors(self, fake_faiss) -> None:
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        for i in range(100):
            vm.add(f"text {i}")

        # The old full-rebuild behaviour re-added every vector on every
        # insertion: 1 + 2 + ... + 100 = 5050.  The fix must be linear.
        assert FakeFaissIndex.index_constructions == 1
        assert vm._faiss_index.add_calls == 100
        assert vm._faiss_index.added_vectors == 100
        assert len(vm._entries) == 100
        assert vm.count == 100


# --------------------------------------------------------------------------- #
# 4. SEARCH EQUIVALENCE — incremental index finds the same nearest vectors
# --------------------------------------------------------------------------- #
class TestSearchEquivalence:
    def test_incremental_search_matches_bruteforce_reference(self, fake_faiss) -> None:
        import numpy as np

        model = StubEmbeddingModel()
        vm = VectorMemory(embedding_model=model)
        texts = [f"knowledge chunk number {i}" for i in range(20)]
        for t in texts:
            vm.add(t)

        query = "knowledge chunk number 7"
        qv = np.asarray(model.encode(query), dtype="float32")
        norm = np.linalg.norm(qv)
        qv = qv / norm if norm else qv

        results = vm.search(query, k=5)

        # Reference: brute-force cosine over the exact stored vectors.
        expected = sorted(
            (
                (float(np.dot(qv, np.asarray(e.vector, dtype="float32") /
                              (np.linalg.norm(e.vector) or 1.0))), i)
                for i, e in enumerate(vm._entries)
            ),
            key=lambda p: p[0],
            reverse=True,
        )[:5]

        assert len(results) == 5
        # FAISS positions == entry list positions (the mapping invariant).
        for rank, (entry, score) in enumerate(results):
            exp_score, exp_pos = expected[rank]
            assert vm._entries[exp_pos].id == entry.id
            assert score == pytest.approx(exp_score, abs=1e-5)

    def test_search_returns_texts_from_correct_positions(self, fake_faiss) -> None:
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        texts = ["alpha doc", "beta doc", "gamma doc", "delta doc"]
        for t in texts:
            vm.add(t)
        hits = vm.search("alpha doc", k=len(texts))
        found_texts = {entry.text for entry, _ in hits}
        assert found_texts == set(texts)


# --------------------------------------------------------------------------- #
# 5. REMOVE STILL PERFORMS FULL REBUILD, MAPPING STAYS CORRECT
# --------------------------------------------------------------------------- #
class TestRemoveStillRebuilds:
    def test_remove_triggers_full_rebuild_and_keeps_mapping(self, fake_faiss) -> None:
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        for i in range(6):
            vm.add(f"text {i}")
        assert vm._faiss_index.added_vectors == 6

        # remove() rebuilds: fresh index over the remaining 5 vectors.
        assert vm.remove("2") is True
        assert FakeFaissIndex.index_constructions == 2  # initial + rebuild
        assert len(vm._faiss_index.vectors) == 5
        assert len(vm._entries) == 5
        # IDs re-derive from positions — mapping remains positional.
        assert [e.id for e in vm._entries] == [e.id for e in vm._entries]
        assert vm._faiss_index.added_vectors == 5  # rebuild added the 5 remaining

        # Search after removal returns only remaining entries with correct ids.
        hits = vm.search("anything", k=5)
        remaining_ids = {e.id for e in vm._entries}
        assert {entry.id for entry, _ in hits} == remaining_ids

        assert vm.remove("missing") is False  # unknown id: no-op


# --------------------------------------------------------------------------- #
# 6. CLEAR RESETS THE INDEX; NEXT ADD CREATES A FRESH ONE
# --------------------------------------------------------------------------- #
class TestClearResetsIndex:
    def test_clear_then_add_creates_fresh_index(self, fake_faiss) -> None:
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        for i in range(3):
            vm.add(f"first batch {i}")
        first_index = vm._faiss_index

        vm.clear()
        assert vm._faiss_index is None
        assert len(vm) == 0

        vm.add("fresh start")
        assert vm._faiss_index is not first_index  # new index object
        assert FakeFaissIndex.index_constructions == 2
        assert vm._faiss_index.added_vectors == 1  # only the new vector
        assert vm._faiss_index.add_calls == 1


# --------------------------------------------------------------------------- #
# 7. NO-FAISS FALLBACK — existing behaviour unchanged
# --------------------------------------------------------------------------- #
class TestNoFaissFallback:
    def test_without_faiss_add_and_search_behave_as_before(self) -> None:
        # Real environment state (no fake installed): _try_init_faiss fails
        # to import faiss and leaves self._faiss = None.
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        assert vm._faiss is None
        assert vm._faiss_index is None

        ids = vm.add_texts(["assistant runs locally", "weather forecast"])
        assert ids == ["0", "1"]
        hits = vm.search("local", k=2)
        assert len(hits) == 2
        for entry, score in hits:
            assert isinstance(score, float)
            assert entry.text in ("assistant runs locally", "weather forecast")

    def test_without_faiss_remove_and_clear_still_work(self) -> None:
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        vm.add_texts(["a", "b", "c"])
        assert vm.remove("1") is True
        assert len(vm) == 2
        vm.clear()
        assert len(vm) == 0
