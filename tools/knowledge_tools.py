"""Knowledge search tool — agent-accessible RAG retrieval.

This tool is a thin adapter over the existing :class:`RAGPipeline`.  It does
**not** reimplement semantic search — it delegates to
``RAGPipeline.retrieve_context()`` which in turn calls
``RAGRetriever.augment()`` -> ``KnowledgeBase.search()`` ->
``VectorMemory.search()``.

The canonical retrieval chain remains:

    KnowledgeSearchTool
      -> RAGPipeline.retrieve_context()
        -> RAGRetriever.augment()
          -> KnowledgeBase.search()
            -> VectorMemory.search()  (semantic / embedding-based)

No new search algorithm is introduced.
"""

from __future__ import annotations

from typing import Any, ClassVar

from core.logger import get_logger
from security.models import ToolCategory
from tools.base import ParameterSpec, RiskLevel, Tool, ToolResult
from tools.models import ToolMetadata, ToolSource, ToolTrust

logger = get_logger("tools.knowledge")


_MAX_TOP_K = 10
_DEFAULT_TOP_K = 3


class KnowledgeSearchTool(Tool):
    """Search the local knowledge base (RAG) and return relevant context.

    The tool delegates entirely to the existing :class:`RAGPipeline`.
    It exposes structured results (doc title, snippet, score) and a
    pre-formatted RAG context string suitable for injection into LLM
    prompts.

    Parameters
    ----------
    rag_pipeline
        The application-wide :class:`RAGPipeline` singleton.  When ``None``
        the tool returns a graceful error rather than raising.
    """

    name = "search_knowledge"
    description = "Search locally indexed knowledge and return relevant passages"
    category: ToolCategory = ToolCategory.GENERAL
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(
            name="query",
            description="Search query (what to look for in the knowledge base)",
        ),
        ParameterSpec(
            name="top_k",
            type="int",
            description="Maximum number of results (1-10, default 3)",
            required=False,
        ),
        ParameterSpec(
            name="project_id",
            description="Project ID (future support — currently unused)",
            required=False,
        ),
    ]
    risk_level = RiskLevel.READ_ONLY

    def __init__(self, rag_pipeline: Any | None = None) -> None:
        self._rag = rag_pipeline

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            tool_id="search_knowledge",
            name="Knowledge Search",
            description="Search the local RAG knowledge base for relevant document snippets.",
            version="1.0.0",
            category=ToolCategory.GENERAL,
            source=ToolSource.BUILTIN,
            risk_level=RiskLevel.READ_ONLY.name.lower(),
            installed=True,
            enabled=True,
            offline=True,
            requires_network=False,
            supported_platforms=("windows", "linux", "macos"),
            permissions=(),
            model_requirements=(),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query text.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results (1-10, default 3).",
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project ID for future scoped search (currently unused).",
                    },
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "doc_title": {"type": "string"},
                                "snippet": {"type": "string"},
                                "score": {"type": "number"},
                            },
                        },
                    },
                    "context": {"type": "string"},
                },
            },
            trust_level=ToolTrust.TRUSTED,
        )

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        query = str(query) if query is not None else ""

        if not query.strip():
            return ToolResult(
                success=False,
                message="Query is required",
                error="EmptyQuery",
                tool_name=self.name,
            )

        if self._rag is None:
            return ToolResult(
                success=False,
                message="Knowledge base is not available",
                error="KnowledgeUnavailable",
                tool_name=self.name,
            )

        top_k = params.get("top_k", _DEFAULT_TOP_K)
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = _DEFAULT_TOP_K
        top_k = max(1, min(top_k, _MAX_TOP_K))

        try:
            results, context = self._rag.retrieve_context(
                query,
                top_k=top_k,
            )
        except Exception as exc:
            logger.exception("KnowledgeSearchTool failed for query: %s", query)
            return ToolResult(
                success=False,
                message=f"Knowledge search failed: {exc}",
                error="SearchError",
                tool_name=self.name,
            )

        structured = []
        for r in results:
            snippet = r.chunk.text.strip().replace("\n", " ")[:500]
            structured.append({
                "doc_title": r.doc_title,
                "snippet": snippet,
                "score": r.score,
            })

        logger.debug(
            "KnowledgeSearchTool: query=%r top_k=%d results=%d",
            query, top_k, len(results),
        )
        return ToolResult(
            success=True,
            message=f"Found {len(results)} relevant results",
            data={
                "query": query,
                "results": structured,
                "context": context,
            },
            tool_name=self.name,
        )
