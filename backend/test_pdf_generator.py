from io import BytesIO

from PyPDF2 import PdfReader

from backend.utils.pdf_generator import ReportData, WskaznikLiczbowy, generate_report_pdf


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
