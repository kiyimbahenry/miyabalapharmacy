from datetime import datetime, timedelta
from django.db.models import Sum, Count, F
from django.utils import timezone
from stock.models import Receipt, Sale, SaleItem, Drug, Invoice, InvoiceItem
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm

def generate_daily_report_pdf(report_date):
    """
    Generate a PDF daily report for a single date.
    
    Args:
        report_date: datetime.date object
    
    Returns:
        BytesIO object containing the PDF
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Header
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20*mm, height - 20*mm, "MIYABALA PHARMACY")
    c.setFont("Helvetica", 12)
    c.drawString(20*mm, height - 30*mm, f"Daily Report - {report_date.strftime('%A, %d %B %Y')}")
    
    # Line
    c.line(20*mm, height - 35*mm, 200*mm, height - 35*mm)
    
    # Sales Summary
    y = height - 50*mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20*mm, y, "Sales Summary")
    
    y -= 10*mm
    receipts = Receipt.objects.filter(created_at__date=report_date)
    total_sales = receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_transactions = receipts.count()
    
    c.setFont("Helvetica", 11)
    c.drawString(25*mm, y, f"Total Sales: {total_sales:,.0f} UGX")
    y -= 7*mm
    c.drawString(25*mm, y, f"Total Transactions: {total_transactions}")
    
    # Payment breakdown
    y -= 10*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25*mm, y, "Payment Breakdown:")
    y -= 7*mm
    c.setFont("Helvetica", 11)
    
    payment_breakdown = receipts.values('payment_method').annotate(
        total=Sum('total_amount'),
        count=Count('id')
    )
    for method in payment_breakdown:
        c.drawString(30*mm, y, f"{method['payment_method'] or 'Unknown'}: {method['total']:,.0f} UGX ({method['count']} txns)")
        y -= 7*mm
    
    # Top Selling Products
    y -= 10*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25*mm, y, "Top Selling Products:")
    y -= 7*mm
    
    top_drugs = {}
    for receipt in receipts:
        if receipt.items:
            for item in receipt.items:
                name = item.get('drug_name', 'Unknown')
                quantity = item.get('quantity', 0)
                if name in top_drugs:
                    top_drugs[name] += quantity
                else:
                    top_drugs[name] = quantity
    
    c.setFont("Helvetica", 10)
    for name, qty in sorted(top_drugs.items(), key=lambda x: x[1], reverse=True)[:10]:
        c.drawString(30*mm, y, f"{name[:30]}: {qty} units")
        y -= 6*mm
    
    # Low Stock Alerts
    y -= 10*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25*mm, y, "Low Stock Alerts:")
    y -= 7*mm
    
    low_stock = Drug.objects.filter(stock_quantity__lte=F('reorder_level'))
    c.setFont("Helvetica", 10)
    if low_stock:
        for drug in low_stock[:10]:
            c.drawString(30*mm, y, f"{drug.name}: {drug.stock_quantity} units (Reorder level: {drug.reorder_level})")
            y -= 6*mm
    else:
        c.drawString(30*mm, y, "All items are adequately stocked.")
    
    # Expiring Drugs
    y -= 10*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25*mm, y, "Expiring Soon (Next 30 days):")
    y -= 7*mm
    
    today = timezone.now().date()
    thirty_days = today + timezone.timedelta(days=30)
    expiring = Drug.objects.filter(expiry_date__gte=today, expiry_date__lte=thirty_days)
    
    c.setFont("Helvetica", 10)
    if expiring:
        for drug in expiring[:10]:
            c.drawString(30*mm, y, f"{drug.name}: {drug.expiry_date.strftime('%d/%m/%Y')}")
            y -= 6*mm
    else:
        c.drawString(30*mm, y, "No drugs expiring in the next 30 days.")
    
    # Footer
    c.setFont("Helvetica", 8)
    c.drawString(20*mm, 15*mm, f"Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    c.drawString(20*mm, 10*mm, "Miyabala Pharmacy - Automated Daily Report")
    
    c.save()
    buffer.seek(0)
    return buffer


def generate_comprehensive_report_pdf(report_date):
    """
    Generate a comprehensive PDF report with all periods:
    Daily, Yesterday, Weekly, Monthly, Annual.
    
    Args:
        report_date: datetime.date object (end date for all periods)
    
    Returns:
        BytesIO object containing the PDF
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Header
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20*mm, height - 20*mm, "MIYABALA PHARMACY")
    c.setFont("Helvetica", 12)
    c.drawString(20*mm, height - 30*mm, f"Comprehensive Report - {report_date.strftime('%A, %d %B %Y')}")
    
    # Line
    c.line(20*mm, height - 35*mm, 200*mm, height - 35*mm)
    
    y = height - 50*mm
    
    # ---- TODAY ----
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.blue)
    c.drawString(20*mm, y, "📊 TODAY'S SALES")
    c.setFillColor(colors.black)
    y -= 10*mm
    
    today = report_date
    daily_receipts = Receipt.objects.filter(created_at__date=today)
    daily_total = daily_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    daily_count = daily_receipts.count()
    
    c.setFont("Helvetica", 11)
    c.drawString(25*mm, y, f"Total Sales: {daily_total:,.0f} UGX")
    y -= 7*mm
    c.drawString(25*mm, y, f"Transactions: {daily_count}")
    y -= 7*mm
    
    # ---- YESTERDAY ----
    y -= 10*mm
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.purple)
    c.drawString(20*mm, y, "📅 YESTERDAY'S SALES")
    c.setFillColor(colors.black)
    y -= 10*mm
    
    yesterday = today - timedelta(days=1)
    yesterday_receipts = Receipt.objects.filter(created_at__date=yesterday)
    yesterday_total = yesterday_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    yesterday_count = yesterday_receipts.count()
    
    c.setFont("Helvetica", 11)
    c.drawString(25*mm, y, f"Total Sales: {yesterday_total:,.0f} UGX")
    y -= 7*mm
    c.drawString(25*mm, y, f"Transactions: {yesterday_count}")
    y -= 7*mm
    
    # ---- WEEKLY ----
    y -= 10*mm
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.green)
    c.drawString(20*mm, y, "📆 WEEKLY SALES")
    c.setFillColor(colors.black)
    y -= 10*mm
    
    week_start = today - timedelta(days=today.weekday())
    weekly_receipts = Receipt.objects.filter(created_at__date__gte=week_start, created_at__date__lte=today)
    weekly_total = weekly_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    weekly_count = weekly_receipts.count()
    
    c.setFont("Helvetica", 11)
    c.drawString(25*mm, y, f"Total Sales: {weekly_total:,.0f} UGX")
    y -= 7*mm
    c.drawString(25*mm, y, f"Transactions: {weekly_count}")
    y -= 7*mm
    c.drawString(25*mm, y, f"Period: {week_start.strftime('%d/%m/%Y')} - {today.strftime('%d/%m/%Y')}")
    y -= 7*mm
    
    # ---- MONTHLY ----
    y -= 10*mm
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.orange)
    c.drawString(20*mm, y, "📊 MONTHLY SALES")
    c.setFillColor(colors.black)
    y -= 10*mm
    
    month_start = today.replace(day=1)
    monthly_receipts = Receipt.objects.filter(created_at__date__gte=month_start, created_at__date__lte=today)
    monthly_total = monthly_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    monthly_count = monthly_receipts.count()
    
    c.setFont("Helvetica", 11)
    c.drawString(25*mm, y, f"Total Sales: {monthly_total:,.0f} UGX")
    y -= 7*mm
    c.drawString(25*mm, y, f"Transactions: {monthly_count}")
    y -= 7*mm
    c.drawString(25*mm, y, f"Month: {month_start.strftime('%B %Y')}")
    y -= 7*mm
    
    # ---- ANNUAL ----
    y -= 10*mm
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.red)
    c.drawString(20*mm, y, "📊 ANNUAL SALES")
    c.setFillColor(colors.black)
    y -= 10*mm
    
    year_start = today.replace(month=1, day=1)
    annual_receipts = Receipt.objects.filter(created_at__date__gte=year_start, created_at__date__lte=today)
    annual_total = annual_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    annual_count = annual_receipts.count()
    
    c.setFont("Helvetica", 11)
    c.drawString(25*mm, y, f"Total Sales: {annual_total:,.0f} UGX")
    y -= 7*mm
    c.drawString(25*mm, y, f"Transactions: {annual_count}")
    y -= 7*mm
    c.drawString(25*mm, y, f"Year: {year_start.year}")
    y -= 7*mm
    
    # ---- LOW STOCK ALERTS ----
    y -= 10*mm
    if y < 40*mm:
        c.showPage()
        y = height - 40*mm
    
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.red)
    c.drawString(20*mm, y, "⚠️ LOW STOCK ALERTS")
    c.setFillColor(colors.black)
    y -= 10*mm
    
    low_stock = Drug.objects.filter(stock_quantity__lte=F('reorder_level'))
    c.setFont("Helvetica", 10)
    if low_stock:
        for drug in low_stock[:10]:
            c.drawString(25*mm, y, f"{drug.name[:30]}: {drug.stock_quantity} units (Reorder: {drug.reorder_level})")
            y -= 6*mm
            if y < 30*mm:
                c.showPage()
                y = height - 40*mm
    else:
        c.drawString(25*mm, y, "✅ All items are adequately stocked.")
    
    # ---- EXPIRING DRUGS ----
    y -= 10*mm
    if y < 40*mm:
        c.showPage()
        y = height - 40*mm
    
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.orange)
    c.drawString(20*mm, y, "⏰ EXPIRING SOON (Next 30 Days)")
    c.setFillColor(colors.black)
    y -= 10*mm
    
    today_date = timezone.now().date()
    thirty_days = today_date + timezone.timedelta(days=30)
    expiring = Drug.objects.filter(expiry_date__gte=today_date, expiry_date__lte=thirty_days)
    
    c.setFont("Helvetica", 10)
    if expiring:
        for drug in expiring[:10]:
            c.drawString(25*mm, y, f"{drug.name[:30]}: {drug.expiry_date.strftime('%d/%m/%Y')}")
            y -= 6*mm
            if y < 30*mm:
                c.showPage()
                y = height - 40*mm
    else:
        c.drawString(25*mm, y, "✅ No drugs expiring in the next 30 days.")
    
    # Footer
    y -= 15*mm
    if y < 30*mm:
        c.showPage()
        y = height - 30*mm
    
    c.setFont("Helvetica", 8)
    c.drawString(20*mm, 15*mm, f"Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    c.drawString(20*mm, 10*mm, "Miyabala Pharmacy - Automated Comprehensive Report")
    
    c.save()
    buffer.seek(0)
    return buffer
