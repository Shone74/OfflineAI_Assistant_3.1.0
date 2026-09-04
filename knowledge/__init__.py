"""Knowledge package — Phase 8: RAG document index, retriever, and pipeline.

Public API:
    DocumentLoader, KnowledgeBase, RAGRetriever, RAGPipeline
    Document, KnowledgeChunk, SearchResult
"""

from knowledge.document_loader import DocumentLoader
from knowledge.knowledge_base import KnowledgeBase
from knowledge.models import Document, KnowledgeChunk, SearchResult
from knowledge.rag_pipeline import RAGPipeline
from knowledge.retriever import RAGRetriever

__all__ = [
    "Document",
    "DocumentLoader",
    "KnowledgeBase",
    "KnowledgeChunk",
    "RAGPipeline",
    "RAGRetriever",
    "SearchResult",
]
