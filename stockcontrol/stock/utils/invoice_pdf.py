from .pdf_generator import generate_invoice_pdf
from django.db.models import Sum
import io
import zipfile

def get_invoice_pdf(invoice_id):
    """
    Get PDF for a specific invoice.
    
    Args:
        invoice_id: The ID of the invoice
    
    Returns:
        BytesIO object containing the PDF
    """
    from stock.models import Invoice, InvoiceItem
    
    invoice = Invoice.objects.get(id=invoice_id)
    items = InvoiceItem.objects.filter(invoice=invoice)
    
    return generate_invoice_pdf(invoice, items)


def get_invoices_zip(report_date):
    """
    Get all invoices for a date as a ZIP file.
    
    Args:
        report_date: datetime.date object
    
    Returns:
        BytesIO object containing the ZIP file
    """
    from stock.models import Invoice, InvoiceItem
    
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zip_file:
        invoices = Invoice.objects.filter(
            invoice_date=report_date
        )
        
        for invoice in invoices:
            items = InvoiceItem.objects.filter(invoice=invoice)
            pdf_buffer = generate_invoice_pdf(invoice, items)
            filename = f"{invoice.invoice_number}.pdf"
            zip_file.writestr(filename, pdf_buffer.getvalue())
    
    buffer.seek(0)
    return buffer


def get_invoices_zip_range(invoices):
    """
    Get multiple invoices as a ZIP file.
    
    Args:
        invoices: Queryset of Invoice objects
    
    Returns:
        BytesIO object containing the ZIP file
    """
    from stock.models import InvoiceItem
    
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zip_file:
        for invoice in invoices:
            items = InvoiceItem.objects.filter(invoice=invoice)
            pdf_buffer = generate_invoice_pdf(invoice, items)
            filename = f"{invoice.invoice_number}.pdf"
            zip_file.writestr(filename, pdf_buffer.getvalue())
    
    buffer.seek(0)
    return buffer
