import io
from pydantic import BaseModel
from typing import List, Optional, Any
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
# reportlab standard fonts don't support full Polish characters smoothly without TTF, 
# but for a provisional report we use the default styles which map to Helvetica.
# If characters are dropped, a specific TTF font like 'DejaVuSans' can be registered later.

class WskaznikLiczbowy(BaseModel):
    nazwa: str
    wartosc: float
    jednostka: str

class ReportData(BaseModel):
    kategoria: Optional[str] = "ESG"
    wskazniki_liczbowe: Optional[List[WskaznikLiczbowy]] = []
    wdrozone_polityki_i_dzialania: Optional[List[str]] = []
    zidentyfikowane_ryzyka: Optional[List[str]] = []
    wnioski_i_zgodnosc_prawna: Optional[str] = ""

def generate_report_pdf(report_data: ReportData) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40, leftMargin=40,
        topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    heading_style = styles['Heading2']
    normal_style = styles['Normal']
    
    # Custom adjustments for provisional report
    title_style.alignment = 1 # Center
    
    elements = []
    
    # 1. Tytuł
    elements.append(Paragraph(f"Raport Prowizoryczny: {report_data.kategoria.upper()}", title_style))
    elements.append(Spacer(1, 20))
    
    # 2. Wskazniki liczbowe (Tabela)
    if report_data.wskazniki_liczbowe:
        elements.append(Paragraph("Wskaźniki Liczbowe", heading_style))
        elements.append(Spacer(1, 10))
        
        table_data = [["Nazwa Wskaźnika", "Wartość", "Jednostka"]]
        for w in report_data.wskazniki_liczbowe:
            table_data.append([w.nazwa, str(w.wartosc), w.jednostka])
            
        table = Table(table_data, colWidths=[250, 100, 100])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 20))
        
    # 3. Wdrożone polityki i działania
    if report_data.wdrozone_polityki_i_dzialania:
        elements.append(Paragraph("Wdrożone Polityki i Działania", heading_style))
        elements.append(Spacer(1, 10))
        for polityka in report_data.wdrozone_polityki_i_dzialania:
            elements.append(Paragraph(f"• {polityka}", normal_style))
            elements.append(Spacer(1, 5))
        elements.append(Spacer(1, 15))
        
    # 4. Zidentyfikowane ryzyka
    if report_data.zidentyfikowane_ryzyka:
        elements.append(Paragraph("Zidentyfikowane Ryzyka", heading_style))
        elements.append(Spacer(1, 10))
        for ryzyko in report_data.zidentyfikowane_ryzyka:
            elements.append(Paragraph(f"• {ryzyko}", normal_style))
            elements.append(Spacer(1, 5))
        elements.append(Spacer(1, 15))
        
    # 5. Wnioski i zgodnosc prawna
    if report_data.wnioski_i_zgodnosc_prawna:
        elements.append(Paragraph("Wnioski i Zgodność Prawna", heading_style))
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(report_data.wnioski_i_zgodnosc_prawna, normal_style))
        
    # Budowanie dokumentu
    doc.build(elements)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
