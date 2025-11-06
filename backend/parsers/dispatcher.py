from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from .base import BaseParser
from .pdf_parser import PdfParser
from .docx_parser import DocxParser
from .tabular_parser import TabularParser


class ParserDispatcher:
    def __init__(self):
        self.parsers: List[BaseParser] = [
            PdfParser(),
            DocxParser(),
            TabularParser(),
        ]

    def get_parser(self, path: Path) -> Optional[BaseParser]:
        for p in self.parsers:
            if p.can_parse(path):
                return p
        return None

    def parse(self, path: Path):
        parser = self.get_parser(path)
        if not parser:
            raise ValueError(f"No parser available for file: {path.name}")
        return parser.parse(path)
