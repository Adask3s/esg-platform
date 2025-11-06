from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
from .base import BaseParser, ParseResult, Table


class TabularParser(BaseParser):
    supported_suffixes = [".csv", ".tsv", ".xlsx", ".xls"]

    def parse(self, path: Path) -> ParseResult:
        result = ParseResult(file_path=path)
        tables: List[Table] = []
        suffix = path.suffix.lower()

        if suffix in {".csv", ".tsv"}:
            sep = "\t" if suffix == ".tsv" else ","
            df = pd.read_csv(path, sep=sep)
            rows = [df.columns.tolist()] + df.fillna("").astype(str).values.tolist()
            tables.append(Table(source="csv", rows=rows))
        elif suffix in {".xlsx", ".xls"}:
            xls = pd.ExcelFile(path)
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                rows = [df.columns.tolist()] + df.fillna("").astype(str).values.tolist()
                tables.append(Table(source=f"sheet:{sheet_name}", rows=rows))
        else:
            raise ValueError(f"Unsupported tabular format: {suffix}")

        result.tables = tables
        result.text = ""  # no plain text for tabular files by default
        result.metadata.update({
            "rows_total": sum(len(t.rows) for t in tables),
            "tables_count": len(tables),
        })
        return result
