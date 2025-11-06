from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import json
import csv
import re
from datetime import datetime

from .base import ParseResult, Table


SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def safe_name(s: str) -> str:
    s = s or "part"
    s = s.replace(" ", "_")
    return SAFE_NAME_RE.sub("_", s)[:80]


def write_result(result: ParseResult, output_root: Path) -> Dict[str, Any]:
    """
    Write parsed content to disk under output_root/<basename>__YYYYmmdd_HHMMSS/.
    Returns a small manifest with paths and counts.
    """
    output_root.mkdir(parents=True, exist_ok=True)

    base = result.file_path.stem
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = output_root / f"{safe_name(base)}__{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "out_dir": str(out_dir),
        "source_file": str(result.file_path),
        "text_file": None,
        "pages_dir": None,
        "tables_dir": None,
        "summary_file": None,
        "counts": {
            "pages": len(result.pages or []),
            "tables": len(result.tables or []),
        },
    }

    # write full text
    if result.text:
        text_path = out_dir / "text.txt"
        text_path.write_text(result.text, encoding="utf-8")
        manifest["text_file"] = str(text_path)

    # write pages
    if result.pages:
        pages_dir = out_dir / "pages"
        pages_dir.mkdir(exist_ok=True)
        for idx, page_text in enumerate(result.pages, start=1):
            (pages_dir / f"page_{idx:03d}.txt").write_text(page_text or "", encoding="utf-8")
        manifest["pages_dir"] = str(pages_dir)

    # write tables as CSV
    if result.tables:
        tables_dir = out_dir / "tables"
        tables_dir.mkdir(exist_ok=True)
        for idx, table in enumerate(result.tables, start=1):
            fname = f"table_{idx:03d}_{safe_name(table.source)}.csv"
            fpath = tables_dir / fname
            with fpath.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for row in table.rows:
                    writer.writerow([(c if c is not None else "") for c in row])
        manifest["tables_dir"] = str(tables_dir)

    # write summary json
    summary = {
        "file": str(result.file_path),
        "metadata": result.metadata,
        "counts": manifest["counts"],
    }
    sum_path = out_dir / "summary.json"
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["summary_file"] = str(sum_path)

    return manifest
