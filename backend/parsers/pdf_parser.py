from __future__ import annotations
from pathlib import Path
from typing import List
from .base import BaseParser, ParseResult, Table


class PdfParser(BaseParser):
    supported_suffixes = [".pdf"]

    def parse(self, path: Path) -> ParseResult:
        import pdfplumber  # lazy import
        result = ParseResult(file_path=path)
        pages_text: List[str] = []
        tables: List[Table] = []

        with pdfplumber.open(str(path)) as pdf:
            meta = pdf.metadata or {}
            if meta:
                result.metadata.update({k: v for k, v in meta.items() if v is not None})

            for i, page in enumerate(pdf.pages, start=1):
                # extract text
                text = page.extract_text() or ""
                pages_text.append(text)

                # attempt to extract tables
                try:
                    page_tables = page.extract_tables() or []
                    for t in page_tables:
                        # normalize None to empty string for CSV friendliness
                        rows = [[cell if cell is not None else "" for cell in row] for row in t]
                        tables.append(Table(source=f"pdf_page_{i}", rows=rows))
                except Exception:
                    # be robust: skip table extraction errors for tricky PDFs
                    pass

        result.pages = pages_text
        result.text = "\n\n".join(pages_text).strip()
        result.tables = tables
        return result
