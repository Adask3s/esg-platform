from __future__ import annotations

import io
import json
import os
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field, field_validator
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


class WskaznikLiczbowy(BaseModel):
    nazwa: str = "Wskaźnik"
    wartosc: Optional[float] = None
    jednostka: Optional[str] = ""

    @field_validator("wartosc", mode="before")
    @classmethod
    def parse_numeric_value(cls, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            normalized = value.replace(" ", "").replace(",", ".")
            match = re.search(r"-?\d+(?:\.\d+)?", normalized)
            return float(match.group(0)) if match else None
        return value


class ReportData(BaseModel):
    kategoria: Optional[str] = "ESG"
    streszczenie_wykonawcze: Optional[str] = ""
    zakres_i_metodyka: Optional[str] = ""
    wskazniki_liczbowe: List[WskaznikLiczbowy] = Field(default_factory=list)
    szczegolowa_analiza: List[str] = Field(default_factory=list)
    wdrozone_polityki_i_dzialania: List[str] = Field(default_factory=list)
    zidentyfikowane_ryzyka: List[str] = Field(default_factory=list)
    luki_w_danych: List[str] = Field(default_factory=list)
    rekomendacje: List[str] = Field(default_factory=list)
    zgodnosc_ze_standardami: List[str] = Field(default_factory=list)
    wnioski_i_zgodnosc_prawna: Optional[str] = ""


class SourceCitation(BaseModel):
    source: str = "Nieznane źródło"
    excerpt: str = ""


PAGE_WIDTH, PAGE_HEIGHT = A4
PALETTE = {
    "navy": HexColor("#1D1F48"),
    "ink": HexColor("#202231"),
    "muted": HexColor("#6B7280"),
    "line": HexColor("#D8D3C8"),
    "paper": HexColor("#F7F5F0"),
    "gold": HexColor("#D9A441"),
    "green": HexColor("#2E7D63"),
    "red": HexColor("#9B2C2C"),
    "soft_gold": HexColor("#F6E8C8"),
    "soft_green": HexColor("#E6F1EC"),
    "soft_red": HexColor("#F4E4E4"),
}


def _candidate_paths(env_name: str, defaults: Sequence[str]) -> list[Path]:
    env_path = os.getenv(env_name)
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend(Path(path) for path in defaults)
    return paths


def _first_existing(paths: Iterable[Path]) -> Optional[Path]:
    for path in paths:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def _register_pdf_fonts() -> tuple[str, str]:
    regular = _first_existing(
        _candidate_paths(
            "ESG_PDF_FONT_REGULAR",
            [
                r"C:\Windows\Fonts\arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
                str(Path(__import__("reportlab").__file__).resolve().parent / "fonts" / "Vera.ttf"),
            ],
        )
    )
    bold = _first_existing(
        _candidate_paths(
            "ESG_PDF_FONT_BOLD",
            [
                r"C:\Windows\Fonts\arialbd.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                str(Path(__import__("reportlab").__file__).resolve().parent / "fonts" / "VeraBd.ttf"),
            ],
        )
    )

    if regular and bold:
        try:
            pdfmetrics.registerFont(TTFont("ESG-Regular", str(regular)))
            pdfmetrics.registerFont(TTFont("ESG-Bold", str(bold)))
            return "ESG-Regular", "ESG-Bold"
        except Exception as exc:
            print(
                f"[pdf_generator] WARNING: TTF font registration failed ({exc}); "
                "Polish glyphs (ł/ć/ż) may not render correctly with Helvetica fallback",
                file=sys.stderr,
            )
            return "Helvetica", "Helvetica-Bold"

    print(
        "[pdf_generator] WARNING: TTF fonts missing or unloadable; "
        "Polish glyphs (ł/ć/ż) may not render correctly with Helvetica fallback",
        file=sys.stderr,
    )
    return "Helvetica", "Helvetica-Bold"


def _load_cover_logo() -> Optional[Image]:
    path = os.getenv("ESG_PDF_LOGO_PATH")
    if not path:
        return None
    try:
        logo_path = Path(path)
        if not logo_path.is_file():
            return None
        reader = ImageReader(str(logo_path))
        width, height = reader.getSize()
        if width <= 0 or height <= 0:
            return None
        max_w, max_h = 35 * mm, 25 * mm
        scale = min(max_w / width, max_h / height)
        return Image(str(logo_path), width=width * scale, height=height * scale)
    except Exception as exc:
        print(f"[pdf_generator] cover logo load failed: {exc}", file=sys.stderr)
        return None


FONT_REGULAR, FONT_BOLD = _register_pdf_fonts()


def _clean_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip() or fallback


def _xml_text(value: Any, fallback: str = "") -> str:
    text = _clean_text(value, fallback)
    return escape(text).replace("\n", "<br/>")


def _truncate(text: str, limit: int) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].strip()
    return f"{clipped}..." if clipped else f"{text[:limit - 3]}..."


def _format_number(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


_RISK_RED = re.compile(
    r"krytyczn|wysokie ryzyko|wysokie zagrożeni|poważn|istotn|niezgod|kara|niedopełn",
    re.IGNORECASE,
)
_RISK_GOLD = re.compile(
    r"średni|umiarkowan|możliw|potencjaln",
    re.IGNORECASE,
)


def _risk_severity(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return "green"
    if _RISK_RED.search(cleaned):
        return "red"
    if _RISK_GOLD.search(cleaned):
        return "gold"
    return "green"


_SEVERITY_BACKGROUNDS = {
    "red": "soft_red",
    "gold": "soft_gold",
    "green": "soft_green",
}


class OutlineEntry(Flowable):
    """Zero-height flowable that registers a PDF bookmark + outline entry on the
    page where it lands. Use one entry per section/subsection."""

    def __init__(self, key: str, title: str, level: int = 0) -> None:
        super().__init__()
        self.key = key
        self.title = title
        self.level = level
        self.width = 0
        self.height = 0

    def wrap(self, _availWidth, _availHeight):  # noqa: D401
        return 0, 0

    def draw(self) -> None:
        canvas = self.canv
        canvas.bookmarkPage(self.key)
        canvas.addOutlineEntry(self.title, self.key, level=self.level, closed=False)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_label": ParagraphStyle(
            "CoverLabel",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=9,
            leading=12,
            textColor=PALETTE["gold"],
            alignment=TA_LEFT,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=34,
            leading=40,
            textColor=PALETTE["navy"],
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName=FONT_REGULAR,
            fontSize=13,
            leading=18,
            textColor=PALETTE["muted"],
            alignment=TA_LEFT,
        ),
        "h2": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=15,
            leading=19,
            textColor=PALETTE["navy"],
            spaceBefore=8,
            spaceAfter=8,
        ),
        "h3": ParagraphStyle(
            "SmallHeading",
            parent=base["Heading3"],
            fontName=FONT_BOLD,
            fontSize=11,
            leading=14,
            textColor=PALETTE["ink"],
            spaceBefore=4,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=13.2,
            textColor=PALETTE["ink"],
            wordWrap="CJK",
        ),
        "body_muted": ParagraphStyle(
            "BodyMuted",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9,
            leading=12,
            textColor=PALETTE["muted"],
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=13,
            leftIndent=13,
            bulletIndent=3,
            textColor=PALETTE["ink"],
            wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["BodyText"],
            fontName=FONT_BOLD,
            fontSize=8.2,
            leading=10,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=8.4,
            leading=10.5,
            textColor=PALETTE["ink"],
            wordWrap="CJK",
        ),
        "table_cell_right": ParagraphStyle(
            "TableCellRight",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=8.4,
            leading=10.5,
            textColor=PALETTE["ink"],
            alignment=TA_RIGHT,
        ),
        "empty": ParagraphStyle(
            "Empty",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=10,
            leading=14,
            textColor=PALETTE["muted"],
            alignment=TA_CENTER,
        ),
    }


def _draw_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(PALETTE["line"])
    canvas.line(doc.leftMargin, 18 * mm, PAGE_WIDTH - doc.rightMargin, 18 * mm)
    canvas.setFillColor(PALETTE["muted"])
    canvas.setFont(FONT_REGULAR, 7.5)
    canvas.drawString(doc.leftMargin, 11 * mm, "ESG Platform")
    canvas.drawCentredString(PAGE_WIDTH / 2, 11 * mm, "Raport wygenerowany automatycznie")
    canvas.drawRightString(PAGE_WIDTH - doc.rightMargin, 11 * mm, f"Strona {doc.page}")
    canvas.restoreState()


def _section_title(number: str, title: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [
            [
                Paragraph(number, styles["table_header"]),
                Paragraph(_xml_text(title), styles["h2"]),
            ]
        ],
        colWidths=[28, 445],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), PALETTE["gold"]),
                ("BACKGROUND", (1, 0), (1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, PALETTE["line"]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _bullet_flowables(items: Sequence[str], empty_message: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    cleaned = [_clean_text(item) for item in items if _clean_text(item)]
    if not cleaned:
        return [Paragraph(_xml_text(empty_message), styles["body_muted"])]
    flowables: list[Any] = []
    for item in cleaned:
        flowables.append(Paragraph(_xml_text(item), styles["bullet"], bulletText="•"))
        flowables.append(Spacer(1, 3))
    return flowables


def _paragraph_flowables(text: Any, empty_message: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    raw_text = _clean_text(text)
    if not raw_text:
        return [Paragraph(_xml_text(empty_message), styles["body_muted"])]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", raw_text) if part.strip()]
    flowables: list[Any] = []
    for paragraph in paragraphs or [raw_text]:
        flowables.append(Paragraph(_xml_text(paragraph), styles["body"]))
        flowables.append(Spacer(1, 8))
    return flowables


def _executive_callout(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    raw = _clean_text(text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip()] or [raw]
    rows = [[Paragraph(_xml_text(paragraph), styles["body"])] for paragraph in paragraphs]
    last_row = len(rows) - 1
    table = Table(rows, colWidths=[473], splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALETTE["soft_gold"]),
                ("LINEBEFORE", (0, 0), (0, -1), 3, PALETTE["gold"]),
                ("LINEABOVE", (0, 0), (-1, 0), 0.3, PALETTE["line"]),
                ("LINEBELOW", (0, last_row), (-1, last_row), 0.3, PALETTE["line"]),
                ("LINEAFTER", (-1, 0), (-1, -1), 0.3, PALETTE["line"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (0, 0), 10),
                ("TOPPADDING", (0, 1), (0, -1), 4),
                ("BOTTOMPADDING", (0, 0), (0, -2), 4),
                ("BOTTOMPADDING", (0, last_row), (-1, last_row), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _risk_callout(text: str, severity: str, styles: dict[str, ParagraphStyle]) -> Table:
    background_key = _SEVERITY_BACKGROUNDS.get(severity, "soft_green")
    inner = Paragraph(_xml_text(text), styles["body"])
    table = Table([[inner]], colWidths=[473])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALETTE[background_key]),
                ("LINEBEFORE", (0, 0), (0, -1), 3, PALETTE[severity]),
                ("BOX", (0, 0), (-1, -1), 0.3, PALETTE["line"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _risk_flowables(items: Sequence[str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    cleaned = [_clean_text(item) for item in items if _clean_text(item)]
    if not cleaned:
        return [Paragraph("Brak zidentyfikowanych ryzyk w dokumentach źródłowych.", styles["body_muted"])]
    flowables: list[Any] = []
    for item in cleaned:
        flowables.append(_risk_callout(item, _risk_severity(item), styles))
        flowables.append(Spacer(1, 6))
    return flowables


def _append_section(
    elements: list[Any],
    number: str,
    title: str,
    styles: dict[str, ParagraphStyle],
    flowables: list[Any],
    *,
    page_break_before: bool = False,
) -> None:
    if page_break_before:
        elements.append(PageBreak())
    elements.append(OutlineEntry(f"sec_{number}", f"{number} {title}", level=0))
    elements.append(_section_title(number, title, styles))
    elements.append(Spacer(1, 10))
    elements.extend(flowables)
    elements.append(Spacer(1, 16))


def _normalize_citations(used_chunks: Any, limit: int = 8) -> list[SourceCitation]:
    if not used_chunks:
        return []

    raw_items: Any = used_chunks
    if isinstance(used_chunks, str):
        try:
            raw_items = json.loads(used_chunks)
        except json.JSONDecodeError:
            raw_items = [used_chunks]

    if not isinstance(raw_items, list):
        raw_items = [raw_items]

    citations: list[SourceCitation] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items:
        source = "Nieznane źródło"
        excerpt = ""

        if isinstance(item, dict):
            source = _clean_text(item.get("source") or item.get("document") or item.get("filename"), source)
            excerpt = _clean_text(item.get("chunk_text") or item.get("text") or item.get("excerpt"))
        else:
            text = _clean_text(item)
            match = re.match(r"^-{3}\s*DOKUMENT:\s*(.*?)\s*-{3}\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                source = _clean_text(match.group(1), source)
                excerpt = _clean_text(match.group(2))
            else:
                excerpt = text

        excerpt = _truncate(excerpt, 380)
        key = (source.lower(), excerpt[:120].lower())
        if excerpt and key not in seen:
            citations.append(SourceCitation(source=source, excerpt=excerpt))
            seen.add(key)

        if len(citations) >= limit:
            break

    return citations


def _build_cover(report_data: ReportData, generated_at: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    category = _clean_text(report_data.kategoria, "ESG")
    meta = [
        [Paragraph("Zakres", styles["table_header"]), Paragraph(_xml_text(category), styles["table_cell"])],
        [Paragraph("Data wygenerowania", styles["table_header"]), Paragraph(_xml_text(generated_at), styles["table_cell"])],
        [Paragraph("Tryb", styles["table_header"]), Paragraph("RAG + LLM + ReportLab PDF", styles["table_cell"])],
    ]
    meta_table = Table(meta, colWidths=[135, 330])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALETTE["navy"]),
                ("BACKGROUND", (1, 0), (1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, PALETTE["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, PALETTE["line"]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    cover: list[Any] = []
    logo = _load_cover_logo()
    if logo is not None:
        cover.extend([Spacer(1, 12), logo, Spacer(1, 18)])
    else:
        cover.append(Spacer(1, 38))

    cover.extend(
        [
            Paragraph("RAPORT ESG", styles["cover_label"]),
            Spacer(1, 10),
            Paragraph("Raport zrównoważonego rozwoju", styles["cover_title"]),
            Paragraph(
                "Automatycznie wygenerowane podsumowanie danych ESG z dokumentów firmy i kontekstu bazy wiedzy.",
                styles["cover_subtitle"],
            ),
            Spacer(1, 32),
            meta_table,
            Spacer(1, 42),
            Table(
                [[Paragraph("Environmental", styles["table_header"]), Paragraph("Social", styles["table_header"]), Paragraph("Governance", styles["table_header"])]],
                colWidths=[150, 150, 150],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, 0), PALETTE["green"]),
                        ("BACKGROUND", (1, 0), (1, 0), PALETTE["gold"]),
                        ("BACKGROUND", (2, 0), (2, 0), PALETTE["navy"]),
                        ("BOX", (0, 0), (-1, -1), 0.5, PALETTE["line"]),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                ),
            ),
            PageBreak(),
        ]
    )
    return cover


def _build_indicator_table(report_data: ReportData, styles: dict[str, ParagraphStyle]) -> list[Any]:
    rows = [
        [
            Paragraph("Wskaźnik", styles["table_header"]),
            Paragraph("Wartość", styles["table_header"]),
            Paragraph("Jednostka", styles["table_header"]),
        ]
    ]
    for indicator in report_data.wskazniki_liczbowe:
        rows.append(
            [
                Paragraph(_xml_text(indicator.nazwa, "Wskaźnik"), styles["table_cell"]),
                Paragraph(_format_number(indicator.wartosc), styles["table_cell_right"]),
                Paragraph(_xml_text(indicator.jednostka, "-"), styles["table_cell"]),
            ]
        )

    if len(rows) == 1:
        return [
            Paragraph(
                "Brak twardych wskaźników liczbowych w dostarczonych dokumentach dla tego zakresu raportu.",
                styles["body_muted"],
            )
        ]

    table = Table(rows, colWidths=[285, 95, 95], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PALETTE["navy"]),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALETTE["paper"]]),
                ("BOX", (0, 0), (-1, -1), 0.6, PALETTE["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, PALETTE["line"]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return [table]


def _build_citations(used_chunks: Any, styles: dict[str, ParagraphStyle]) -> list[Any]:
    citations = _normalize_citations(used_chunks)
    if not citations:
        return [Paragraph("Brak zapisanych cytowań z RAG dla tego raportu.", styles["body_muted"])]

    rows = [
        [
            Paragraph("Lp.", styles["table_header"]),
            Paragraph("Źródło", styles["table_header"]),
            Paragraph("Fragment", styles["table_header"]),
        ]
    ]
    flowables: list[Any] = []
    for index, citation in enumerate(citations, start=1):
        rows.append(
            [
                Paragraph(str(index), styles["table_cell_right"]),
                Paragraph(_xml_text(citation.source), styles["table_cell"]),
                Paragraph(_xml_text(citation.excerpt), styles["table_cell"]),
            ]
        )
        title = _truncate(f"Źródło {index}: {citation.source}", 80)
        flowables.append(OutlineEntry(f"cit_{index}", title, level=1))

    table = Table(rows, colWidths=[32, 145, 298], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PALETTE["navy"]),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALETTE["paper"]]),
                ("BOX", (0, 0), (-1, -1), 0.6, PALETTE["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, PALETTE["line"]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    flowables.append(table)
    return flowables


def generate_report_pdf(
    report_data: ReportData,
    used_chunks: Any = None,
    generated_at: Optional[str] = None,
) -> bytes:
    generated_at = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    styles = _styles()
    category = _clean_text(report_data.kategoria, "ESG")
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=26 * mm,
        title=f"Raport ESG - {category}",
        author="ESG Platform",
    )

    has_report_data = any(
        [
            _clean_text(report_data.streszczenie_wykonawcze),
            _clean_text(report_data.zakres_i_metodyka),
            report_data.wskazniki_liczbowe,
            report_data.szczegolowa_analiza,
            report_data.wdrozone_polityki_i_dzialania,
            report_data.zidentyfikowane_ryzyka,
            report_data.luki_w_danych,
            report_data.rekomendacje,
            report_data.zgodnosc_ze_standardami,
            _clean_text(report_data.wnioski_i_zgodnosc_prawna),
        ]
    )
    has_citations = bool(_normalize_citations(used_chunks))

    elements: list[Any] = []
    elements.extend(_build_cover(report_data, generated_at, styles))

    executive_summary = _clean_text(report_data.streszczenie_wykonawcze) or _clean_text(
        report_data.wnioski_i_zgodnosc_prawna
    )
    if executive_summary:
        a1_flowables: list[Any] = [_executive_callout(executive_summary, styles)]
    else:
        a1_flowables = [
            Paragraph(
                "Brak streszczenia wykonawczego w danych raportu.",
                styles["body_muted"],
            )
        ]
    _append_section(
        elements,
        "A1",
        "Streszczenie wykonawcze",
        styles,
        a1_flowables,
    )
    _append_section(
        elements,
        "A2",
        "Zakres i metodyka",
        styles,
        _paragraph_flowables(
            report_data.zakres_i_metodyka,
            "Raport powstał na podstawie dokumentów użytkownika oraz kontekstu bazy wiedzy ESG. Brak dodatkowego opisu metodyki.",
            styles,
        ),
    )
    _append_section(
        elements,
        "A3",
        "Szczegółowa analiza",
        styles,
        _bullet_flowables(
            report_data.szczegolowa_analiza,
            "Brak szczegółowej analizy w danych raportu.",
            styles,
        ),
        page_break_before=True,
    )
    _append_section(
        elements,
        "A4",
        "Luki w danych",
        styles,
        _bullet_flowables(
            report_data.luki_w_danych,
            "Brak wskazanych luk w danych.",
            styles,
        ),
    )
    _append_section(
        elements,
        "A5",
        "Rekomendacje",
        styles,
        _bullet_flowables(
            report_data.rekomendacje,
            "Brak rekomendacji w danych raportu.",
            styles,
        ),
        page_break_before=True,
    )
    _append_section(
        elements,
        "A6",
        "Zgodność ze standardami",
        styles,
        _bullet_flowables(
            report_data.zgodnosc_ze_standardami,
            "Brak oceny zgodności ze standardami w danych raportu.",
            styles,
        ),
    )

    if has_report_data:
        elements.append(PageBreak())

        elements.append(OutlineEntry("sec_01", "01 Wskaźniki liczbowe", level=0))
        elements.append(_section_title("01", "Wskaźniki liczbowe", styles))
        elements.append(Spacer(1, 10))
        elements.extend(_build_indicator_table(report_data, styles))
        elements.append(Spacer(1, 18))

        elements.append(OutlineEntry("sec_02", "02 Wdrożone polityki i działania", level=0))
        elements.append(_section_title("02", "Wdrożone polityki i działania", styles))
        elements.append(Spacer(1, 10))
        elements.extend(
            _bullet_flowables(
                report_data.wdrozone_polityki_i_dzialania,
                "Brak zidentyfikowanych polityk lub działań w dokumentach źródłowych.",
                styles,
            )
        )
        elements.append(Spacer(1, 14))

        elements.append(OutlineEntry("sec_03", "03 Zidentyfikowane ryzyka", level=0))
        elements.append(_section_title("03", "Zidentyfikowane ryzyka", styles))
        elements.append(Spacer(1, 10))
        elements.extend(_risk_flowables(report_data.zidentyfikowane_ryzyka, styles))
        elements.append(Spacer(1, 14))

        elements.append(OutlineEntry("sec_04", "04 Wnioski i zgodność prawna", level=0))
        elements.append(_section_title("04", "Wnioski i zgodność prawna", styles))
        elements.append(Spacer(1, 10))
        if _clean_text(report_data.wnioski_i_zgodnosc_prawna):
            elements.append(Paragraph(_xml_text(report_data.wnioski_i_zgodnosc_prawna), styles["body"]))
        else:
            elements.append(Paragraph("Brak wniosków prawnych dla tego raportu.", styles["body_muted"]))
        elements.append(Spacer(1, 18))

        elements.append(OutlineEntry("sec_05", "05 Źródła i cytowania RAG", level=0))
        elements.append(_section_title("05", "Źródła i cytowania RAG", styles))
        elements.append(Spacer(1, 10))
        elements.extend(_build_citations(used_chunks, styles))
    else:
        elements.append(PageBreak())
        elements.append(OutlineEntry("sec_empty", "Brak wystarczających danych", level=0))
        elements.append(_section_title("!", "Brak wystarczających danych", styles))
        elements.append(Spacer(1, 10))
        elements.append(
            Paragraph(
                "System nie znalazł wystarczających danych z dokumentów firmy, aby przygotować pełny raport dla wybranego zakresu. "
                "Dodaj dokumenty z konkretnymi wskaźnikami lub wygeneruj raport dla szerszego zakresu ESG.",
                styles["empty"],
            )
        )
        elements.append(Spacer(1, 20))
        if has_citations:
            elements.append(OutlineEntry("sec_05", "05 Źródła i cytowania RAG", level=0))
            elements.append(_section_title("05", "Źródła i cytowania RAG", styles))
            elements.append(Spacer(1, 10))
            elements.extend(_build_citations(used_chunks, styles))

    def _draw_chrome(canvas, doc, _category=category):
        _draw_footer(canvas, doc)
        if doc.page > 1:
            canvas.saveState()
            canvas.setFont(FONT_REGULAR, 7.5)
            canvas.setFillColor(PALETTE["muted"])
            canvas.drawString(
                doc.leftMargin,
                PAGE_HEIGHT - 14 * mm,
                f"{_category} — Raport ESG",
            )
            canvas.restoreState()

    doc.build(elements, onFirstPage=_draw_chrome, onLaterPages=_draw_chrome)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
