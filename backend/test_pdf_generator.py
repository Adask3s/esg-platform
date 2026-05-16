import struct
import zlib
from io import BytesIO

from PyPDF2 import PdfReader

from backend.utils import pdf_generator as pdf_module
from backend.utils.pdf_generator import (
    ReportData,
    WskaznikLiczbowy,
    _register_pdf_fonts,
    _risk_severity,
    generate_report_pdf,
)


def _flatten_outline(items, depth=0):
    flat = []
    for item in items:
        if isinstance(item, list):
            flat.extend(_flatten_outline(item, depth + 1))
        else:
            title = getattr(item, "title", None) or item.get("/Title")
            if title is not None:
                flat.append(str(title))
    return flat


def _read_outline_titles(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf_bytes))
    outline = reader.outline if hasattr(reader, "outline") else reader.getOutlines()
    return _flatten_outline(outline)


def _extract_page_text(pdf_bytes: bytes, page_index: int) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    if page_index >= len(reader.pages):
        return ""
    return reader.pages[page_index].extract_text() or ""


def _all_page_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _write_minimal_png(path) -> None:
    """Tiny valid 1x1 grayscale PNG."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    iend = chunk(b"IEND", b"")
    path.write_bytes(signature + ihdr + idat + iend)


def _rich_report() -> ReportData:
    return ReportData(
        kategoria="ESG",
        streszczenie_wykonawcze=(
            "Raport wskazuje na istotne dane we wszystkich filarach ESG. "
            "Organizacja posiada mierzalne dane środowiskowe, społeczne i zarządcze."
        ),
        zakres_i_metodyka="Raport oparto na dokumentach firmy oraz bazie wiedzy.",
        wskazniki_liczbowe=[
            WskaznikLiczbowy(nazwa="Emisje", wartosc=100, jednostka="tCO2e"),
        ],
        szczegolowa_analiza=["Analiza środowiskowa."],
        wdrozone_polityki_i_dzialania=["Polityka recyklingu."],
        zidentyfikowane_ryzyka=[
            "Krytyczne ryzyko kary finansowej za niedopełnienie obowiązków.",
            "Średni wpływ regulacyjny na koszty operacyjne.",
            "Pozytywny trend wzrostu recyklingu na placach budowy.",
        ],
        luki_w_danych=["Brak danych Scope 3."],
        rekomendacje=["Uzupełnić dane podwykonawców."],
        zgodnosc_ze_standardami=["GRI 305 wymaga uzupełnień."],
        wnioski_i_zgodnosc_prawna="Firma wymaga uzupełnienia danych.",
    )


def test_generate_report_pdf_returns_pdf_with_citations():
    report = ReportData(
        kategoria="Environmental",
        wskazniki_liczbowe=[
            WskaznikLiczbowy(nazwa="Emisje CO2", wartosc=123.4, jednostka="tCO2e"),
            WskaznikLiczbowy(nazwa="Recykling", wartosc="42,5%", jednostka="%"),
        ],
        wdrozone_polityki_i_dzialania=["Polityka recyklingu na budowie"],
        zidentyfikowane_ryzyka=["Brak pelnych danych Scope 3"],
        wnioski_i_zgodnosc_prawna="Dane wymagaja uzupelnienia przed raportowaniem.",
    )

    pdf = generate_report_pdf(
        report,
        used_chunks=["--- DOKUMENT: raport.pdf ---\nFragment zrodlowy do cytowania."],
        generated_at="2026-05-15 12:00",
    )

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000
    assert len(PdfReader(BytesIO(pdf)).pages) >= 2


def test_generate_report_pdf_handles_empty_report():
    pdf = generate_report_pdf(ReportData(kategoria="ESG"), generated_at="2026-05-15 12:00")

    assert pdf.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(pdf)).pages) >= 2


def test_generate_report_pdf_renders_rich_report_on_multiple_pages():
    report = ReportData(
        kategoria="ESG",
        streszczenie_wykonawcze=(
            "Raport wskazuje na istotne dane we wszystkich filarach ESG. "
            "Organizacja posiada mierzalne dane środowiskowe, społeczne i zarządcze."
        ),
        zakres_i_metodyka=(
            "Raport przygotowano na podstawie dokumentów użytkownika oraz kontekstu bazy wiedzy. "
            "Wskaźniki liczbowe pochodzą wyłącznie z dokumentów firmy."
        ),
        wskazniki_liczbowe=[
            WskaznikLiczbowy(nazwa="Emisje Scope 1", wartosc=4860, jednostka="tCO2e"),
            WskaznikLiczbowy(nazwa="Godziny szkoleń BHP", wartosc=8920, jednostka="h"),
            WskaznikLiczbowy(nazwa="Audyty", wartosc=9, jednostka="szt."),
        ],
        szczegolowa_analiza=[
            "Analiza środowiskowa pokazuje wpływ zużycia paliw, energii oraz gospodarki odpadami.",
            "Analiza społeczna obejmuje pracowników, bezpieczeństwo pracy, szkolenia i relacje z otoczeniem.",
            "Analiza governance wskazuje na audyty, zgodność, procedury zakupowe i zgłoszenia naruszeń.",
        ],
        wdrozone_polityki_i_dzialania=[
            "Wdrożono harmonogram pracy agregatów i odzysk wody technologicznej.",
            "Zastosowano system punktacji BHP dla podwykonawców.",
        ],
        zidentyfikowane_ryzyka=[
            "Ryzyko niepełnych danych Scope 3.",
            "Ryzyko niespójnej ewidencji podwykonawców.",
        ],
        luki_w_danych=["Brakuje pełnego rozbicia emisji według dostawców."],
        rekomendacje=[
            "Ujednolicić formularze danych ESG dla podwykonawców.",
            "Zwiększyć udział materiałów z deklaracjami EPD.",
        ],
        zgodnosc_ze_standardami=["Dane wspierają raportowanie GRI i ESRS, ale wymagają uzupełnień."],
        wnioski_i_zgodnosc_prawna="Firma ma podstawę do raportowania, ale powinna poprawić kompletność danych.",
    )

    pdf = generate_report_pdf(
        report,
        used_chunks=["--- DOKUMENT: test.docx ---\nDane źródłowe z dokumentu testowego."],
        generated_at="2026-05-15 12:00",
    )

    assert pdf.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(pdf)).pages) >= 4


def test_outline_has_section_bookmarks():
    pdf = generate_report_pdf(
        _rich_report(),
        used_chunks=["--- DOKUMENT: test.docx ---\nDane źródłowe z dokumentu testowego."],
        generated_at="2026-05-15 12:00",
    )
    titles = _read_outline_titles(pdf)
    joined = " | ".join(titles)
    assert "Streszczenie wykonawcze" in joined
    assert "Zgodność ze standardami" in joined
    assert "Źródła i cytowania RAG" in joined
    assert len(titles) >= 11


def test_risk_severity_routing():
    assert _risk_severity("Krytyczne ryzyko ekspozycji walutowej") == "red"
    assert _risk_severity("Średni wpływ regulacyjny na koszty") == "gold"
    assert _risk_severity("Pozytywny trend wzrostu recyklingu") == "green"
    assert _risk_severity("") == "green"


def test_executive_callout_renders_long_summary():
    paragraph = "Streszczenie wykonawcze opisuje istotne dane finansowe i operacyjne. " * 12
    summary = "\n\n".join([paragraph] * 6)  # 6 akapitów, wymusza split między stronami
    report = _rich_report()
    report.streszczenie_wykonawcze = summary

    pdf = generate_report_pdf(report, generated_at="2026-05-15 12:00")

    assert pdf.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(pdf)).pages) >= 3
    assert "Streszczenie wykonawcze opisuje" in _all_page_text(pdf)


def test_logo_missing_path_does_not_break(monkeypatch):
    monkeypatch.setenv("ESG_PDF_LOGO_PATH", "/nonexistent/path/that/does/not/exist.png")
    pdf = generate_report_pdf(_rich_report(), generated_at="2026-05-15 12:00")
    assert pdf.startswith(b"%PDF-")


def test_logo_valid_path_increases_pdf_size(monkeypatch, tmp_path):
    monkeypatch.delenv("ESG_PDF_LOGO_PATH", raising=False)
    baseline = generate_report_pdf(_rich_report(), generated_at="2026-05-15 12:00")

    logo_path = tmp_path / "logo.png"
    _write_minimal_png(logo_path)
    monkeypatch.setenv("ESG_PDF_LOGO_PATH", str(logo_path))
    with_logo = generate_report_pdf(_rich_report(), generated_at="2026-05-15 12:00")

    assert with_logo.startswith(b"%PDF-")
    assert len(with_logo) > len(baseline) + 100


def test_empty_state_skips_data_sections():
    pdf = generate_report_pdf(ReportData(kategoria="ESG"), generated_at="2026-05-15 12:00")
    text = _all_page_text(pdf)
    assert "Brak wystarczających danych" in text
    assert "Wskaźniki liczbowe" not in text
    assert "Wdrożone polityki" not in text


def test_running_header_present_on_page_2_only():
    pdf = generate_report_pdf(_rich_report(), generated_at="2026-05-15 12:00")
    page1 = _extract_page_text(pdf, 0)
    page2 = _extract_page_text(pdf, 1)
    assert "ESG — Raport ESG" in page2
    assert "ESG — Raport ESG" not in page1


def test_citation_bookmarks_emitted():
    pdf = generate_report_pdf(
        _rich_report(),
        used_chunks=[
            "--- DOKUMENT: report-a.docx ---\nFragment pierwszy do cytowania.",
            "--- DOKUMENT: report-b.docx ---\nFragment drugi do cytowania.",
        ],
        generated_at="2026-05-15 12:00",
    )
    titles = _read_outline_titles(pdf)
    assert any(title.startswith("Źródło 1") for title in titles)
    assert any(title.startswith("Źródło 2") for title in titles)


def test_font_fallback_warns_when_ttf_missing(monkeypatch, capsys):
    monkeypatch.setattr(pdf_module, "_first_existing", lambda _paths: None)
    regular, bold = _register_pdf_fonts()
    assert regular == "Helvetica"
    assert bold == "Helvetica-Bold"
    captured = capsys.readouterr()
    assert "Polish glyphs" in captured.err
