from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs" / "pdf"


def first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def register_fonts() -> tuple[str, str, str]:
    regular = first_existing(
        [
            Path(r"C:\Windows\Fonts\arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        ]
    )
    bold = first_existing(
        [
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        ]
    )
    mono = first_existing(
        [
            Path(r"C:\Windows\Fonts\consola.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf"),
        ]
    )
    if regular:
        pdfmetrics.registerFont(TTFont("Doc-Regular", str(regular)))
    if bold:
        pdfmetrics.registerFont(TTFont("Doc-Bold", str(bold)))
    if mono:
        pdfmetrics.registerFont(TTFont("Doc-Mono", str(mono)))
    return (
        "Doc-Regular" if regular else "Helvetica",
        "Doc-Bold" if bold else "Helvetica-Bold",
        "Doc-Mono" if mono else "Courier",
    )


FONT_REGULAR, FONT_BOLD, FONT_MONO = register_fonts()


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=22,
            leading=27,
            textColor=colors.HexColor("#1D1F48"),
            spaceAfter=14,
            alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName=FONT_BOLD,
            fontSize=18,
            leading=23,
            textColor=colors.HexColor("#1D1F48"),
            spaceBefore=10,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#202231"),
            spaceBefore=9,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName=FONT_BOLD,
            fontSize=11.5,
            leading=15,
            textColor=colors.HexColor("#202231"),
            spaceBefore=7,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.2,
            leading=12.7,
            textColor=colors.HexColor("#202231"),
            spaceAfter=6,
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9,
            leading=12.4,
            leftIndent=15,
            bulletIndent=5,
            textColor=colors.HexColor("#202231"),
            spaceAfter=4,
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName=FONT_MONO,
            fontSize=7.2,
            leading=9.2,
            leftIndent=0,
            rightIndent=0,
            textColor=colors.HexColor("#111827"),
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=7.6,
            leading=9.5,
            textColor=colors.HexColor("#374151"),
            wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["BodyText"],
            fontName=FONT_BOLD,
            fontSize=7.1,
            leading=8.8,
            textColor=colors.white,
            wordWrap="CJK",
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=7,
            leading=8.7,
            textColor=colors.HexColor("#202231"),
            wordWrap="CJK",
        ),
    }


def md_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r'<font name="%s">\1</font>' % FONT_MONO, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return escaped


def is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    chars = set(stripped.replace("|", "").replace(":", "").replace("-", "").strip())
    return not chars


def split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def markdown_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT)
        rel_parts = set(rel.parts)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ".venv" in rel_parts or "node_modules" in rel_parts:
            continue
        if "docs" in rel_parts and "pdf" in rel_parts:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix().lower())


def output_name(path: Path) -> str:
    rel = path.relative_to(ROOT)
    if rel.parent == Path("."):
        return f"{path.stem}.pdf"
    if rel.parent == Path("docs"):
        return f"{path.stem}.pdf"
    return f"{'_'.join(rel.with_suffix('').parts)}.pdf"


def add_code_block(elements: list, code: str, style_map: dict[str, ParagraphStyle]) -> None:
    wrapped_lines: list[str] = []
    for line in code.splitlines() or [""]:
        if len(line) <= 105:
            wrapped_lines.append(line)
        else:
            wrapped_lines.extend(textwrap.wrap(line, width=105, replace_whitespace=False, drop_whitespace=False))
    pre = Preformatted("\n".join(wrapped_lines), style_map["code"], maxLineLength=110)
    table = Table([[pre]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 5))


def add_table(elements: list, rows: list[list[str]], style_map: dict[str, ParagraphStyle]) -> None:
    if not rows:
        return
    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    width = 170 * mm
    col_width = width / max_cols
    data = []
    for row_idx, row in enumerate(normalized):
        row_style = style_map["table_header"] if row_idx == 0 else style_map["table_cell"]
        data.append([Paragraph(md_inline(cell), row_style) for cell in row])
    table = Table(data, colWidths=[col_width] * max_cols, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1D1F48")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F5F0")]),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 7))


def build_pdf(md_path: Path, pdf_path: Path) -> None:
    style_map = styles()
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = next((line.lstrip("#").strip() for line in lines if line.startswith("# ")), md_path.stem)

    elements: list = [
        Paragraph(md_inline(title), style_map["title"]),
        Paragraph(f"Source: {md_path.relative_to(ROOT).as_posix()}", style_map["small"]),
        Spacer(1, 8),
    ]

    paragraph: list[str] = []
    table_rows: list[list[str]] = []
    in_code = False
    code_lines: list[str] = []
    code_lang = ""

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            elements.append(Paragraph(md_inline(" ".join(paragraph).strip()), style_map["body"]))
            paragraph = []

    def flush_table() -> None:
        nonlocal table_rows
        if table_rows:
            add_table(elements, table_rows, style_map)
            table_rows = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.startswith("```"):
            if in_code:
                prefix = f"[{code_lang}]\n" if code_lang else ""
                add_code_block(elements, prefix + "\n".join(code_lines), style_map)
                code_lines = []
                code_lang = ""
                in_code = False
            else:
                flush_paragraph()
                flush_table()
                in_code = True
                code_lang = line.strip("`").strip()
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_paragraph()
            flush_table()
            continue

        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            if not is_table_separator(line):
                table_rows.append(split_table_row(line))
            continue
        else:
            flush_table()

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            content = heading.group(2).strip()
            if level == 1:
                elements.append(PageBreak())
                elements.append(Paragraph(md_inline(content), style_map["h1"]))
            elif level == 2:
                elements.append(Paragraph(md_inline(content), style_map["h2"]))
            else:
                elements.append(Paragraph(md_inline(content), style_map["h3"]))
            continue

        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        ordered = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if bullet or ordered:
            flush_paragraph()
            content = (bullet or ordered).group(1)
            marker = "-" if bullet else "•"
            elements.append(Paragraph(md_inline(content), style_map["bullet"], bulletText=marker))
            continue

        if line.startswith(">"):
            flush_paragraph()
            elements.append(Paragraph(md_inline(line.lstrip("> ").strip()), style_map["body"]))
            continue

        paragraph.append(line.strip())

    flush_paragraph()
    flush_table()
    if in_code:
        add_code_block(elements, "\n".join(code_lines), style_map)

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="JKPSZ3 ESG Platform",
    )
    doc.build(elements)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = []
    for md_path in markdown_files():
        pdf_path = OUT_DIR / output_name(md_path)
        build_pdf(md_path, pdf_path)
        generated.append(pdf_path.relative_to(ROOT).as_posix())
    print("\n".join(generated))


if __name__ == "__main__":
    main()
