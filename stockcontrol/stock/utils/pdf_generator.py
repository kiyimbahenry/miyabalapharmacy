from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from datetime import datetime
import io

def generate_invoice_pdf(invoice, items):
    """
    Generate a PDF invoice for a supplier purchase invoice.
    
    Args:
        invoice: Invoice model instance
        items: Queryset of InvoiceItem objects
    
    Returns:
        BytesIO object containing the PDF
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20*mm, height - 20*mm, "MIYABALA PHARMACY")
    
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, height - 25*mm, "Phone: +256 XXX XXX XXX")
    c.drawString(20*mm, height - 30*mm, "Email: info@miyabalapharmacy.com")
    
    # Invoice title
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20*mm, height - 40*mm, "PURCHASE INVOICE")
    
    # Invoice details
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, height - 48*mm, f"Invoice #: {invoice.invoice_number}")
    c.drawString(20*mm, height - 53*mm, f"Date: {invoice.invoice_date.strftime('%d/%m/%Y')}")
    c.drawString(20*mm, height - 58*mm, f"Supplier: {invoice.supplier.name}")
    
    # Table header
    c.setFont("Helvetica-Bold", 10)
    y = height - 75*mm
    c.drawString(20*mm, y, "Drug")
    c.drawString(80*mm, y, "Quantity")
    c.drawString(130*mm, y, "Unit Price (UGX)")
    c.drawString(180*mm, y, "Total (UGX)")
    
    # Line
    c.line(20*mm, y - 2*mm, 200*mm, y - 2*mm)
    
    # Table data
    c.setFont("Helvetica", 9)
    y -= 8*mm
    for item in items:
        drug_name = item.drug.name[:30]
        c.drawString(20*mm, y, drug_name)
        c.drawString(80*mm, y, str(item.quantity))
        c.drawString(130*mm, y, f"{item.unit_price:,.0f}")
        c.drawString(180*mm, y, f"{item.total:,.0f}")
        y -= 6*mm
        if y < 20*mm:
            c.showPage()
            y = height - 40*mm
    
    # Total
    y -= 5*mm
    c.line(20*mm, y + 3*mm, 200*mm, y + 3*mm)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(130*mm, y, "TOTAL:")
    c.drawString(180*mm, y, f"{invoice.total_amount:,.0f} UGX")
    
    c.save()
    buffer.seek(0)
    return buffer
