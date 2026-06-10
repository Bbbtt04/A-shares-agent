from __future__ import annotations

from .base import BaseListRetriever


class StructuredRetriever(BaseListRetriever):
    retrieval_method = "structured"
