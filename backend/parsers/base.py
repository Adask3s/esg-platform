from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class Table:
    source: str  # e.g., "pdf_page_3", "docx_table_1", "sheet:Sheet1"
    rows: List[List[Any]]


@dataclass
class ParseResult:
    file_path: Path
    text: str = ""
    pages: List[str] = field(default_factory=list)  # per-page text if available
    tables: List[Table] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseParser:
    """Abstract base class for all parsers."""

    supported_suffixes: List[str] = []

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_suffixes

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError
