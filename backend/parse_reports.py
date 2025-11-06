from __future__ import annotations
import argparse
from pathlib import Path
from typing import List
import sys

# Local imports
from parsers.dispatcher import ParserDispatcher
from parsers.output_writer import write_result


SUPPORTED_SUFFIXES = {".pdf", ".docx", ".csv", ".tsv", ".xlsx", ".xls"}


def find_files(inputs: List[Path]) -> List[Path]:
    files: List[Path] = []
    for p in inputs:
        if p.is_file():
            if p.suffix.lower() in SUPPORTED_SUFFIXES:
                files.append(p)
        elif p.is_dir():
            for ext in SUPPORTED_SUFFIXES:
                files.extend(p.rglob(f"*{ext}"))
        else:
            print(f"[WARN] Path not found: {p}")
    # de-duplicate while preserving order
    seen = set()
    unique: List[Path] = []
    for f in files:
        sp = f.resolve()
        if sp not in seen:
            seen.add(sp)
            unique.append(f)
    return unique


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Parse ESG reports into text/tables for inspection.")
    parser.add_argument("inputs", nargs="+", help="Files or folders to parse (pdf, docx, csv, xlsx, xls)")
    parser.add_argument("--out", dest="out", default=None, help="Output root directory (default: output_test_parser at repo root)")

    args = parser.parse_args(argv)

    # resolve project root = two levels up from this file (backend/)
    project_root = Path(__file__).resolve().parents[1]
    out_root = Path(args.out) if args.out else project_root / "output_test_parser"

    inputs = [Path(p) for p in args.inputs]
    files = find_files(inputs)
    if not files:
        print("No supported files found.")
        return 1

    dispatcher = ParserDispatcher()

    print(f"Found {len(files)} file(s). Output -> {out_root}")
    for f in files:
        try:
            result = dispatcher.parse(f)
            manifest = write_result(result, out_root)
            print(f"[OK] {f.name} -> {manifest['out_dir']}")
        except Exception as e:
            print(f"[ERROR] {f}: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
