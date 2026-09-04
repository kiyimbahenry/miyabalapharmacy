from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Sum, F, ExpressionWrapper, DecimalField, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.mail import send_mail, get_connection, EmailMessage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.management import call_command
from django.db import transaction
from django.db import models
import json
import os
import base64
import traceback
import logging
from datetime import datetime, timedelta
from decimal import Decimal

# Brevo / Sendinblue
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

# Your utils
from .utils.invoice_pdf import get_invoices_zip, get_invoices_zip_range
from .utils.report_generator import generate_daily_report_pdf, generate_comprehensive_report_pdf

# IMPORTS
from .models import (
    Drug, Supplier, Invoice, Category, InvoiceItem,
    Sale, SaleItem, Receipt, Report, ChronicPatient,
    PatientMedication, PatientVisit,
    ReturnedDrug, StockMovement, CreditSale, CreditPayment
)

# FORM IMPORTS
from .forms import SupplierForm, InvoiceForm, DrugForm, StockMovementForm

# Set up logger
logger = logging.getLogger(__name__)


def is_admin_or_manager(user):
    """Return True if user is superuser or belongs to 'admin' or 'manager' group."""
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=['admin', 'manager']).exists()


# ============================================================
# AUTO SYNC CREDIT RECEIPTS - ADDED
# ============================================================

def auto_sync_credit_receipts():
    """Automatically sync credit receipts to CreditSale records"""
    credit_receipts = Receipt.objects.filter(
        payment_method__icontains='credit',
        credit_sale__isnull=True
    )
    
    created = 0
    for receipt in credit_receipts:
        try:
            remaining = receipt.total_amount - receipt.amount_paid
            
            if remaining <= 0:
                status = 'paid'
            elif receipt.amount_paid > 0:
                status = 'partial'
            else:
                status = 'pending'
            
            # Count existing credits for today
            today_count = CreditSale.objects.filter(
                created_at__date=receipt.created_at.date()
            ).count()
            
            credit_sale = CreditSale.objects.create(
                credit_receipt_number=f"CR-{receipt.created_at.strftime('%Y%m%d')}-{today_count + 1:04d}",
                customer_name=receipt.customer_name or "Walk-in Customer",
                customer_phone=receipt.customer_phone or "",
                total_amount=receipt.total_amount,
                amount_paid=receipt.amount_paid,
                remaining_balance=max(remaining, Decimal('0.00')),
                payment_method=receipt.payment_method,
                items=receipt.items or [],
                due_date=receipt.created_at.date() + timedelta(days=30),
                status=status,
                created_by=receipt.created_by,
                created_at=receipt.created_at
            )
            
            receipt.credit_sale = credit_sale
            receipt.is_credit = True
            receipt.save()
            created += 1
            
            if receipt.amount_paid > 0:
                CreditPayment.objects.create(
                    credit_sale=credit_sale,
                    amount=receipt.amount_paid,
                    payment_method=receipt.payment_method,
                    reference=f"Initial payment from receipt {receipt.receipt_number}",
                    created_by=receipt.created_by,
                    created_at=receipt.created_at
                )
            
            print(f"✅ Auto-synced: {receipt.receipt_number} → {credit_sale.credit_receipt_number}")
        except Exception as e:
            print(f"❌ Error syncing {receipt.receipt_number}: {str(e)}")
    
    return created


# ============================================================
# SEND REPORT EMAIL - COMPLETE VERSION
# ============================================================

def send_report_email(report_data, email, report_type):
    try:
        import base64
        from datetime import datetime, timedelta
        from django.utils import timezone
        from .utils.invoice_pdf import get_invoices_zip, get_invoices_zip_range
        from .utils.report_generator import generate_daily_report_pdf, generate_comprehensive_report_pdf
        from stock.models import Invoice

        report_date = report_data.get('report_date')
        if isinstance(report_date, str):
            report_date = datetime.strptime(report_date, "%Y-%m-%d").date()
        if report_date is None:
            report_date = timezone.localdate()

        print("===== BREVO API EMAIL =====")
        print("Recipient:", email)
        print("Report Type:", report_type)
        print(f"📅 Report Date: {report_date}")

        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = os.environ.get("BREVO_API_KEY")

        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )

        if report_type == 'daily':
            start_date = report_date
            end_date = report_date
        elif report_type == 'weekly':
            end_date = report_date
            start_date = end_date - timedelta(days=7)
        elif report_type == 'monthly':
            end_date = report_date
            start_date = end_date.replace(day=1)
        elif report_type == 'annual':
            end_date = report_date
            start_date = end_date.replace(month=1, day=1)
        else:
            start_date = report_date
            end_date = report_date

        sales = report_data.get("sales", {})
        invoices_data = report_data.get("invoices", {})
        payment_breakdown = report_data.get("payment_breakdown", [])
        top_products = report_data.get("top_products", [])
        credit_sales = report_data.get("credit_sales", {})
        period = report_data.get("period", f"{report_type.capitalize()} Report")
        generated_at = report_data.get("generated_at", timezone.now().strftime('%Y-%m-%d %H:%M:%S'))

        pdf_buffer = generate_comprehensive_report_pdf(report_date)
        pdf_encoded = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')

        if report_type == 'daily':
            zip_buffer = get_invoices_zip(report_date)
        else:
            invoices_qs = Invoice.objects.filter(
                invoice_date__gte=start_date,
                invoice_date__lte=end_date
            )
            zip_buffer = get_invoices_zip_range(invoices_qs)

        zip_encoded = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')

        payment_rows = ""
        for method in payment_breakdown:
            payment_rows += f"""
            <tr>
                <td>{method.get('method', 'Unknown')}</td>
                <td>UGX {method.get('total', 0):,.0f}</td>
                <td>{method.get('count', 0)}</td>
            </tr>
            """

        product_rows = ""
        for i, product in enumerate(top_products[:10], 1):
            product_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{product.get('name', 'Unknown')}</td>
                <td>{product.get('quantity', 0)}</td>
                <td>UGX {product.get('total', 0):,.0f}</td>
            </tr>
            """

        subject = f"{report_type.capitalize()} Sales Report - Miyabala Pharmacy"

        html_content = f"""
        <html>
        <head>
        <style>
            body {{
                font-family: Arial, Helvetica, sans-serif;
                background: #f4f6f9;
                padding: 30px;
            }}
            .container {{
                max-width: 700px;
                margin: auto;
                background: white;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 0 10px rgba(0,0,0,.15);
            }}
            .header {{
                background: #0b7d3b;
                color: white;
                text-align: center;
                padding: 25px;
            }}
            .header h1 {{
                margin: 0;
            }}
            .header h3 {{
                margin-top: 8px;
                font-weight: normal;
            }}
            .section {{
                padding: 25px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th {{
                background: #0b7d3b;
                color: white;
                padding: 12px;
                text-align: left;
            }}
            td {{
                border: 1px solid #ddd;
                padding: 12px;
            }}
            .footer {{
                background: #f1f1f1;
                text-align: center;
                padding: 20px;
                color: #666;
                font-size: 14px;
            }}
            .attachments {{
                background: #ebf8ff;
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
                border-left: 4px solid #0b7d3b;
            }}
            .attachments ul {{
                margin: 5px 0;
                padding-left: 20px;
            }}
            .attachments li {{
                margin: 3px 0;
            }}
        </style>
        </head>

        <body>
        <div class="container">
            <div class="header">
                <h1>🏥 MIYABALA PHARMACY</h1>
                <h3>{report_type.capitalize()} Sales Report</h3>
            </div>
            <div class="section">
                <p><strong>Report Period:</strong> {period}</p>
                <p><strong>Generated:</strong> {generated_at}</p>
                <table>
                    <tr><th>Description</th><th>Value</th></tr>
                    <tr><td>Total Sales</td><td>UGX {sales.get('total_amount', 0):,.0f}</td></tr>
                    <tr><td>Net Sales</td><td>UGX {sales.get('net_sales', 0):,.0f}</td></tr>
                    <tr><td>Total Returns</td><td>UGX {sales.get('total_returns', 0):,.0f}</td></tr>
                    <tr><td>Total Transactions</td><td>{sales.get('total_transactions', 0)}</td></tr>
                    <tr><td>Total Medicines Sold</td><td>{sales.get('total_items_sold', 0)}</td></tr>
                    <tr><td>Total Invoices</td><td>{invoices_data.get('total_invoices', 0)}</td></tr>
                    <tr><td>Average Transaction</td><td>UGX {sales.get('average_transaction', 0):,.0f}</td></tr>
                </table>

                <h3 style="margin-top: 30px;">💳 Payment Breakdown</h3>
                <table>
                    <tr><th>Method</th><th>Amount</th><th>Transactions</th></tr>
                    {payment_rows}
                </table>

                <h3 style="margin-top: 30px;">📊 Credit Sales</h3>
                <table>
                    <tr><th>Description</th><th>Value</th></tr>
                    <tr><td>Total Credit Sales</td><td>UGX {credit_sales.get('total_credit_amount', 0):,.0f}</td></tr>
                    <tr><td>Total Paid</td><td>UGX {credit_sales.get('total_credit_paid', 0):,.0f}</td></tr>
                    <tr><td>Total Outstanding</td><td>UGX {credit_sales.get('total_credit_outstanding', 0):,.0f}</td></tr>
                    <tr><td>Total Credit Transactions</td><td>{credit_sales.get('total_credit_transactions', 0)}</td></tr>
                    <tr><td>Overdue Credits</td><td>{credit_sales.get('overdue_count', 0)}</td></tr>
                </table>

                <h3 style="margin-top: 30px;">🏆 Top Selling Products</h3>
                <table>
                    <tr><th>#</th><th>Product</th><th>Quantity</th><th>Total</th></tr>
                    {product_rows}
                </table>

                <div class="attachments">
                    <h3>📎 Attachments</h3>
                    <ul>
                        <li><strong>📄 Daily_Report_{report_date.strftime('%Y-%m-%d')}.pdf</strong> – Full report with all details</li>
                        <li><strong>📦 Invoices_{report_date.strftime('%Y-%m-%d')}.zip</strong> – All purchase invoices</li>
                    </ul>
                </div>
            </div>
            <div class="footer">
                <b>Miyabala Pharmacy Stock Management System</b>
                <br><br>
                This report was generated automatically.
            </div>
        </div>
        </body>
        </html>
        """

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[
                {"email": "kiyimbahenry314@gmail.com", "name": "Henry"},
                {"email": "daveedaviyam@gmail.com", "name": "David"}
            ],
            sender={
                "name": "Miyabala Pharmacy",
                "email": "kiyimbahenry314@gmail.com"
            },
            subject=subject,
            html_content=html_content,
            attachment=[
                {
                    "content": pdf_encoded,
                    "name": f"Daily_Report_{report_date.strftime('%Y-%m-%d')}.pdf"
                },
                {
                    "content": zip_encoded,
                    "name": f"Invoices_{report_date.strftime('%Y-%m-%d')}.zip"
                }
            ]
        )

        response = api_instance.send_transac_email(send_smtp_email)
        print("✅ EMAIL SENT SUCCESSFULLY via Brevo!")
        return True

    except ApiException as e:
        print("❌ BREVO API ERROR")
        print(e.body)
        return False
    except Exception as e:
        print("❌ GENERAL ERROR")
        print(str(e))
        traceback.print_exc()
        return False


# ============================================================
# DAILY REPORT
# ============================================================

@csrf_exempt
def run_daily_report(request):
    """Endpoint to trigger daily report via cron-job.org"""
    if request.method not in ['GET', 'POST']:
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        today = timezone.now().date()
        report_data = generate_report_data('daily', today)
        success = send_report_email(report_data, 'kiyimbahenry314@gmail.com', 'daily')
        
        if success:
            return JsonResponse({'success': True, 'message': 'Daily report sent successfully'})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to send email'}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def test_smtp(request):
    try:
        connection = get_connection()
        connection.open()
        connection.close()
        return JsonResponse({
            "success": True,
            "host": settings.EMAIL_HOST,
            "port": settings.EMAIL_PORT,
            "user": settings.EMAIL_HOST_USER,
            "use_tls": settings.EMAIL_USE_TLS,
        })
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "host": settings.EMAIL_HOST,
            "port": settings.EMAIL_PORT,
            "user": settings.EMAIL_HOST_USER,
            "use_tls": settings.EMAIL_USE_TLS,
        }, status=500)


# ============================================================
# AUTHENTICATION VIEWS
# ============================================================

def login_view(request):
    """User login view - supports both username and email"""
    if request.user.is_authenticated:
        return redirect('stock:dashboard')

    if request.method == 'POST':
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')

        if username_or_email and password:
            user = None

            if '@' in username_or_email:
                try:
                    user_obj = User.objects.get(email=username_or_email)
                    user = authenticate(request, username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass

            if not user:
                user = authenticate(request, username=username_or_email, password=password)

            if user is not None:
                login(request, user)
                next_url = request.GET.get('next', '/')
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid email/username or password.')
        else:
            messages.error(request, 'Please enter both email/username and password.')

    return render(request, 'stock/login.html')


def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('stock:login')


# ============================================================
# DASHBOARD VIEW
# ============================================================

@login_required
def dashboard(request):
    """
    Dashboard view showing statistics and recent data
    """
    today = timezone.now().date()

    # Get statistics
    total_medicines = Drug.objects.count()
    total_suppliers = Supplier.objects.count()
    total_invoices = Invoice.objects.count()
    low_stock_count = Drug.objects.filter(stock_quantity__lt=10).count()

    # Get recent medicines (last 5)
    recent_medicines = Drug.objects.all().order_by('-id')[:5]

    # Calculate total stock value
    all_drugs = Drug.objects.all()
    total_stock_value = 0
    for drug in all_drugs:
        total_stock_value += drug.stock_quantity * drug.selling_price

    # ---- OUT OF STOCK COUNT ----
    out_of_stock_count = Drug.objects.filter(stock_quantity=0).count()
    expired_out_of_stock_count = Drug.objects.filter(
        expiry_date__lt=today,
        stock_quantity=0
    ).count()
    total_out_of_stock = out_of_stock_count + expired_out_of_stock_count

    # ---- TODAY'S SALES ----
    today_receipts = Receipt.objects.filter(created_at__date=today)
    today_sales = (
        today_receipts.aggregate(Sum('total_amount'))['total_amount__sum']
        or Decimal("0.00")
    )
    today_transactions = today_receipts.count()

    # ---- TODAY'S CREDIT SALES ----
    today_credit_sales = CreditSale.objects.filter(created_at__date=today)
    today_credit_total = (
        today_credit_sales.aggregate(Sum('total_amount'))['total_amount__sum']
        or Decimal("0.00")
    )
    today_credit_count = today_credit_sales.count()

    # ---- TODAY'S RETURNS ----
    today_returns = ReturnedDrug.objects.filter(returned_date__date=today)
    today_returns_amount = (
        today_returns.aggregate(Sum('total_refund'))['total_refund__sum']
        or Decimal("0.00")
    )
    today_returns_count = today_returns.count()

    # ---- NET SALES (Sales - Returns) ----
    net_sales = today_sales - today_returns_amount

    # ---- TOP SELLING PRODUCTS TODAY ----
    top_drugs = {}
    for receipt in today_receipts:
        if receipt.items:
            for item in receipt.items:
                name = item.get('drug_name', 'Unknown')
                quantity = item.get('quantity', 0)
                if name in top_drugs:
                    top_drugs[name] += quantity
                else:
                    top_drugs[name] = quantity

    top_selling = sorted(top_drugs.items(), key=lambda x: x[1], reverse=True)[:5]

    # ---- TOTAL OUTSTANDING CREDIT ----
    total_outstanding = CreditSale.objects.filter(
        status__in=['pending', 'partial']
    ).aggregate(
        total=Sum('remaining_balance')
    )['total'] or Decimal("0.00")

    # ---- OVERDUE CREDIT SALES ----
    overdue_credits = CreditSale.objects.filter(
        status__in=['pending', 'partial'],
        due_date__lt=today
    ).count()

    context = {
        'total_medicines': total_medicines,
        'total_suppliers': total_suppliers,
        'total_invoices': total_invoices,
        'low_stock_count': low_stock_count,
        'recent_medicines': recent_medicines,
        'total_stock_value': total_stock_value,
        'total_out_of_stock': total_out_of_stock,
        'today_sales': today_sales,
        'today_transactions': today_transactions,
        'today_returns': today_returns_amount,
        'today_returns_count': today_returns_count,
        'net_sales': net_sales,
        'top_selling': top_selling,
        'today_credit_total': today_credit_total,
        'today_credit_count': today_credit_count,
        'total_outstanding': total_outstanding,
        'overdue_credits': overdue_credits,
    }

    return render(request, 'stock/dashboard.html', context)


# ============================================================
# API VIEWS FOR DASHBOARD
# ============================================================

@login_required
def get_drugs_api(request):
    """API for dashboard short expiry with pagination."""
    try:
        today = timezone.now().date()
        drugs_qs = Drug.objects.filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
        ).order_by('expiry_date')

        page = request.GET.get('page', 1)
        paginator = Paginator(drugs_qs, 10)
        try:
            drugs_page = paginator.page(page)
        except (PageNotAnInteger, EmptyPage):
            drugs_page = paginator.page(1)

        data = []
        for drug in drugs_page:
            data.append({
                'id': drug.id,
                'generic': drug.generic_name if drug.generic_name else drug.name,
                'brand': drug.brand if drug.brand else 'N/A',
                'strength': getattr(drug, 'strength', 'N/A'),
                'expiry': drug.expiry_date.strftime('%Y-%m-%d') if drug.expiry_date else 'N/A',
                'qty': drug.stock_quantity,
                'price': float(drug.selling_price) if drug.selling_price else 0,
                'batch_no': drug.batch_no if drug.batch_no else 'N/A',
            })

        return JsonResponse({
            'data': data,
            'page': drugs_page.number,
            'total_pages': paginator.num_pages,
            'has_next': drugs_page.has_next(),
            'has_previous': drugs_page.has_previous(),
        }, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e), 'message': 'Error fetching drugs data'}, status=500)


@login_required
def get_all_drugs_for_sale(request):
    """API endpoint for sale form – returns all active drugs as a flat list (no pagination)."""
    try:
        today = timezone.now().date()
        drugs_qs = Drug.objects.filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
        ).order_by('expiry_date')
        data = []
        for drug in drugs_qs:
            data.append({
                'id': drug.id,
                'name': drug.name,
                'generic': drug.generic_name,
                'brand': drug.brand,
                'price': float(drug.selling_price),
                'qty': drug.stock_quantity,
                'batch_no': drug.batch_no,
                'expiry': drug.expiry_date.strftime('%Y-%m-%d') if drug.expiry_date else None,
            })
        return JsonResponse(data, safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================
# AUTOCOMPLETE API
# ============================================================

@login_required
def autocomplete_drugs(request):
    """API endpoint for drug autocomplete."""
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)

    drugs = Drug.objects.filter(
        Q(name__icontains=query) |
        Q(brand__icontains=query) |
        Q(generic_name__icontains=query)
    ).order_by('name')[:20]

    data = [{
        'id': d.id,
        'name': d.name,
        'brand': d.brand or '',
        'generic_name': d.generic_name or '',
        'stock_quantity': d.stock_quantity,
        'pack_size': d.pack_size,
        'cost_price': float(d.cost_price),
        'selling_price': float(d.selling_price),
    } for d in drugs]

    return JsonResponse(data, safe=False)


# ============================================================
# COMPLETE SALE - FIXED WITH CLEAR_CART
# ============================================================

@login_required
def complete_sale(request):
    """API endpoint to complete a drug sale and update stock"""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method. Use POST.',
        }, status=400)

    try:
        print("=" * 60)
        print("COMPLETE SALE REQUEST RECEIVED")
        print(f"Request method: {request.method}")
        print(f"Content-Type: {request.content_type}")

        data = json.loads(request.body)
        print(f"Parsed data: {json.dumps(data, indent=2)}")
        print("=" * 60)

        items = []

        if 'items' in data and isinstance(data['items'], list):
            items = data['items']
            print(f"Format 1: Found {len(items)} items in 'items' array")
        elif 'drug_id' in data or 'drug_name' in data:
            item = {}
            if 'drug_id' in data:
                item['drug_id'] = data['drug_id']
            if 'drug_name' in data:
                item['drug_name'] = data['drug_name']
            if 'name' in data:
                item['drug_name'] = data['name']
            item['quantity'] = data.get('quantity', 0)
            items.append(item)
            print(f"Format 2: Single item: {item}")
        elif 'cart' in data and isinstance(data['cart'], list):
            for cart_item in data['cart']:
                item = {}
                if 'drug_id' in cart_item:
                    item['drug_id'] = cart_item['drug_id']
                if 'drug_name' in cart_item:
                    item['drug_name'] = cart_item['drug_name']
                if 'name' in cart_item:
                    item['drug_name'] = cart_item['name']
                item['quantity'] = cart_item.get('quantity', cart_item.get('qty', 0))
                items.append(item)
            print(f"Format 3: Found {len(items)} items in 'cart' array")

        if not items:
            return JsonResponse({
                'success': False,
                'message': 'No items found in request.',
                'received_data': data,
                'available_keys': list(data.keys())
            }, status=400)

        customer_name = data.get('customer_name', 'Walk-in Customer')
        customer_phone = data.get('customer_phone', '')
        amount_paid = float(data.get('amount_paid', 0))
        payment_method = data.get('payment_method', 'cash')
        sale_type = data.get('sale_type', 'retail')

        # Credit sale fields
        is_credit = data.get('is_credit', False)
        due_date = data.get('due_date')
        credit_limit = data.get('credit_limit', 0)

        sale_items = []
        total_amount = 0

        for idx, item in enumerate(items):
            drug_id = item.get('drug_id')
            drug_name = item.get('drug_name') or item.get('name')
            quantity = int(item.get('quantity', 0))

            print(f"Processing item {idx + 1}: drug_id={drug_id}, drug_name={drug_name}, quantity={quantity}")

            if quantity <= 0:
                print(f"  ⚠️ Skipping item with quantity {quantity}")
                continue

            drug = None

            if drug_id:
                try:
                    drug = Drug.objects.get(id=drug_id)
                    print(f"  ✅ Found by ID {drug_id}: {drug.name}")
                except Drug.DoesNotExist:
                    print(f"  ❌ No drug with ID {drug_id}")

            if not drug and drug_name:
                try:
                    drug = Drug.objects.get(name__iexact=drug_name)
                    print(f"  ✅ Found by exact name: {drug.name}")
                except Drug.DoesNotExist:
                    drug = Drug.objects.filter(
                        Q(name__icontains=drug_name) |
                        Q(generic_name__icontains=drug_name)
                    ).first()
                    if drug:
                        print(f"  ✅ Found by contains match: {drug.name}")
                    else:
                        print(f"  ❌ No drug with name containing '{drug_name}'")

            if not drug:
                available_drugs = list(Drug.objects.all().values_list('name', flat=True)[:20])
                return JsonResponse({
                    'success': False,
                    'message': f'Drug not found: {drug_name or drug_id}',
                    'search_term': drug_name or drug_id,
                    'available_drugs': available_drugs,
                    'total_drugs': Drug.objects.count()
                }, status=404)

            if drug.stock_quantity < quantity:
                return JsonResponse({
                    'success': False,
                    'message': f'Insufficient stock for {drug.name}. Available: {drug.stock_quantity}, Requested: {quantity}',
                    'drug_id': drug.id,
                    'drug_name': drug.name,
                    'available': drug.stock_quantity,
                    'requested': quantity
                }, status=400)

            drug.stock_quantity -= quantity
            drug.save()
            print(f"  ✅ Updated stock for {drug.name}: {drug.stock_quantity} remaining")

            item_total = drug.selling_price * quantity
            total_amount += item_total

            sale_items.append({
                'drug_id': drug.id,
                'drug_name': drug.name,
                'quantity': quantity,
                'unit_price': float(drug.selling_price),
                'total': float(item_total)
            })

        if not sale_items:
            return JsonResponse({
                'success': False,
                'message': 'No valid items to process after validation'
            }, status=400)

        # ============================================================
        # Handle Credit Sale - FIXED with clear_cart signal
        # ============================================================
        if is_credit:
            # For credit sales, amount_paid should be 0 (customer pays later)
            credit_amount_paid = amount_paid if amount_paid > 0 else 0

            print(f"Creating credit sale: total={total_amount}, paid={credit_amount_paid}")

            # Create credit sale
            credit_sale = CreditSale.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                total_amount=total_amount,
                amount_paid=credit_amount_paid,
                remaining_balance=total_amount - credit_amount_paid,
                payment_method='credit',
                items=sale_items,
                due_date=due_date or (timezone.now().date() + timedelta(days=30)),
                credit_limit=credit_limit,
                status=(
                    'paid' if credit_amount_paid >= total_amount
                    else 'partial' if credit_amount_paid > 0
                    else 'pending'
                ),
                created_by=request.user
            )

            print(f"✅ CreditSale created: {credit_sale.credit_receipt_number}")

            # Record the payment if any was made
            if credit_amount_paid > 0:
                CreditPayment.objects.create(
                    credit_sale=credit_sale,
                    amount=credit_amount_paid,
                    payment_method=payment_method,
                    reference=f"Initial payment - {payment_method}",
                    created_by=request.user
                )
                print(f"✅ CreditPayment created: UGX {credit_amount_paid}")

            # ALWAYS CREATE A RECEIPT
            receipt = Receipt.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                total_amount=total_amount,
                amount_paid=credit_amount_paid,
                change_due=0,
                payment_method='credit',
                items=sale_items,
                created_by=request.user,
                is_credit=True,
                credit_sale=credit_sale
            )

            print(f"✅ Receipt created: {receipt.receipt_number}")

            return JsonResponse({
                'success': True,
                'message': 'Credit sale created successfully!',
                'is_credit': True,
                'credit_sale_id': credit_sale.id,
                'receipt_id': receipt.id,
                'receipt_number': receipt.receipt_number,
                'credit_receipt_number': credit_sale.credit_receipt_number,
                'total_amount': float(total_amount),
                'amount_paid': float(credit_amount_paid),
                'remaining_balance': float(credit_sale.remaining_balance),
                'due_date': credit_sale.due_date.strftime('%Y-%m-%d') if credit_sale.due_date else None,
                'items': sale_items,
                'credit_url': f'/credits/{credit_sale.id}/',
                'receipt_url': f'/receipts/{receipt.id}/',
                'clear_cart': True  # Signal to clear the cart
            })

        # Regular sale (cash/mobile/card)
        change_due = amount_paid - total_amount if amount_paid > total_amount else 0

        receipt = Receipt.objects.create(
            customer_name=customer_name,
            customer_phone=customer_phone,
            total_amount=total_amount,
            amount_paid=amount_paid,
            change_due=change_due,
            payment_method=payment_method,
            items=sale_items,
            created_by=request.user,
            is_credit=False
        )

        print(f"✅ Sale completed successfully!")
        print(f"   Receipt #{receipt.receipt_number}")
        print(f"   Total: UGX {total_amount}")
        print("=" * 60)

        return JsonResponse({
            'success': True,
            'message': 'Sale completed successfully!',
            'receipt_id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'total_amount': float(total_amount),
            'amount_paid': float(amount_paid),
            'change_due': float(change_due),
            'items': sale_items,
            'receipt_url': f'/receipts/{receipt.id}/',
            'clear_cart': True  # Signal to clear the cart
        })

    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Invalid JSON data: {str(e)}',
            'received': request.body.decode('utf-8', errors='ignore')
        }, status=400)
    except Exception as e:
        print(f"❌ Sale error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'Error processing sale: {str(e)}'
        }, status=500)


# ============================================================
# CREDIT SALE VIEWS
# ============================================================

@login_required
def credit_list(request):
    """List only active (unpaid) credit sales with filtering and pagination"""
    # Only show pending and partial credits (active credits)
    credits = CreditSale.objects.filter(
        status__in=['pending', 'partial']
    ).select_related('created_by').order_by('-created_at')

    # Filter by status (optional - allows viewing paid credits)
    status_filter = request.GET.get('status')
    if status_filter == 'all':
        credits = CreditSale.objects.all().select_related('created_by').order_by('-created_at')
    elif status_filter:
        credits = credits.filter(status=status_filter)

    # Filter by date range
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        credits = credits.filter(created_at__date__gte=date_from)
    if date_to:
        credits = credits.filter(created_at__date__lte=date_to)

    # Search by customer name or phone
    search_query = request.GET.get('search')
    if search_query:
        credits = credits.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(credit_receipt_number__icontains=search_query)
        )

    # Pagination
    paginator = Paginator(credits, 20)
    page = request.GET.get('page')
    try:
        credits_page = paginator.page(page)
    except PageNotAnInteger:
        credits_page = paginator.page(1)
    except EmptyPage:
        credits_page = paginator.page(paginator.num_pages)

    # Statistics (only from active credits)
    total_outstanding = CreditSale.objects.filter(
        status__in=['pending', 'partial']
    ).aggregate(
        total=Sum('remaining_balance')
    )['total'] or Decimal("0.00")

    overdue_count = CreditSale.objects.filter(
        status__in=['pending', 'partial'],
        due_date__lt=timezone.now().date()
    ).count()

    total_credit_sales = CreditSale.objects.aggregate(
        total=Sum('total_amount')
    )['total'] or Decimal("0.00")

    total_paid = CreditSale.objects.aggregate(
        total=Sum('amount_paid')
    )['total'] or Decimal("0.00")

    paid_count = CreditSale.objects.filter(status='paid').count()

    context = {
        'credits': credits_page,
        'status_filter': status_filter,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'total_outstanding': total_outstanding,
        'overdue_count': overdue_count,
        'total_credit_sales': total_credit_sales,
        'total_paid': total_paid,
        'paid_count': paid_count,
        'status_choices': CreditSale.STATUS_CHOICES,
    }
    return render(request, 'stock/credit_list.html', context)


@login_required
def credit_detail(request, credit_id):
    """View credit sale details"""
    credit = get_object_or_404(CreditSale, id=credit_id)
    payments = credit.payments.all().order_by('-created_at')
    return render(request, 'stock/credit_detail.html', {
        'credit': credit,
        'payments': payments,
    })


@login_required
def credit_payment(request, credit_id):
    """Record a payment for a credit sale"""
    credit = get_object_or_404(CreditSale, id=credit_id)

    if credit.status == 'paid':
        messages.warning(request, 'This credit sale is already fully paid.')
        return redirect('stock:credit_list')

    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', 0))
            payment_method = request.POST.get('payment_method', 'cash')
            reference = request.POST.get('reference', '')

            if amount <= 0:
                messages.error(request, 'Payment amount must be greater than zero.')
                return redirect('stock:credit_detail', credit_id=credit.id)

            if amount > credit.remaining_balance:
                messages.error(request, f'Payment amount cannot exceed remaining balance of UGX {credit.remaining_balance:,.0f}.')
                return redirect('stock:credit_detail', credit_id=credit.id)

            # Create the payment record
            CreditPayment.objects.create(
                credit_sale=credit,
                amount=amount,
                payment_method=payment_method,
                reference=reference or f"Payment - {payment_method}",
                created_by=request.user
            )

            # RECALCULATE from all payments
            total_paid = credit.payments.aggregate(models.Sum('amount'))['amount__sum'] or Decimal('0.00')

            credit.amount_paid = total_paid
            credit.remaining_balance = credit.total_amount - total_paid

            if credit.remaining_balance <= 0:
                credit.status = 'paid'
                credit.remaining_balance = Decimal("0.00")
                messages.success(request, f'✅ Credit #{credit.credit_receipt_number} is now fully paid!')
                return redirect('stock:credit_list')
            else:
                credit.status = 'partial'

            credit.save()

            messages.success(request, f'Payment of UGX {amount:,.0f} recorded successfully!')
            return redirect('stock:credit_detail', credit_id=credit.id)

        except Exception as e:
            messages.error(request, f'Error recording payment: {str(e)}')
            import traceback
            traceback.print_exc()
            return redirect('stock:credit_detail', credit_id=credit.id)

    return render(request, 'stock/credit_payment.html', {'credit': credit})


@login_required
def credit_delete(request, credit_id):
    """Delete a credit sale (admin only)"""
    credit = get_object_or_404(CreditSale, id=credit_id)

    if not is_admin_or_manager(request.user):
        messages.error(request, 'You do not have permission to delete credit sales.')
        return redirect('stock:credit_list')

    if request.method == 'POST':
        try:
            credit_number = credit.credit_receipt_number
            credit.delete()
            messages.success(request, f'Credit sale #{credit_number} deleted successfully!')
            return redirect('stock:credit_list')
        except Exception as e:
            messages.error(request, f'Error deleting credit sale: {str(e)}')
            return redirect('stock:credit_list')

    return render(request, 'stock/credit_confirm_delete.html', {'credit': credit})


@login_required
def get_credit_summary_api(request):
    """API endpoint to get credit sales summary"""
    try:
        today = timezone.now().date()

        total_outstanding = CreditSale.objects.filter(
            status__in=['pending', 'partial']
        ).aggregate(
            total=Sum('remaining_balance')
        )['total'] or Decimal("0.00")

        overdue_count = CreditSale.objects.filter(
            status__in=['pending', 'partial'],
            due_date__lt=today
        ).count()

        today_credits = CreditSale.objects.filter(created_at__date=today)
        today_total = today_credits.aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal("0.00")
        today_count = today_credits.count()

        recent_credits = CreditSale.objects.filter(
            status__in=['pending', 'partial']
        ).order_by('-created_at')[:10]

        recent_data = []
        for credit in recent_credits:
            recent_data.append({
                'id': credit.id,
                'credit_receipt_number': credit.credit_receipt_number,
                'customer_name': credit.customer_name,
                'total_amount': float(credit.total_amount),
                'remaining_balance': float(credit.remaining_balance),
                'due_date': credit.due_date.strftime('%Y-%m-%d') if credit.due_date else None,
                'status': credit.status,
                'created_at': credit.created_at.strftime('%Y-%m-%d %H:%M'),
            })

        return JsonResponse({
            'success': True,
            'total_outstanding': float(total_outstanding),
            'overdue_count': overdue_count,
            'today_total': float(today_total),
            'today_count': today_count,
            'recent_credits': recent_data,
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ============================================================
# DRUG (MEDICINE) VIEWS
# ============================================================

@login_required
def drug_list(request):
    """List all drugs/medicines with summary totals, exclude expired, paginated."""
    today = timezone.now().date()

    drugs_qs = Drug.objects.filter(
        Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
    ).select_related('category', 'supplier').order_by('generic_name')

    category_id = request.GET.get('category')
    if category_id:
        drugs_qs = drugs_qs.filter(category_id=category_id)

    search_query = request.GET.get('search')
    if search_query:
        drugs_qs = drugs_qs.filter(
            Q(name__icontains=search_query) |
            Q(generic_name__icontains=search_query) |
            Q(brand__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    categories = Category.objects.all()

    paginator = Paginator(drugs_qs, 10)
    page = request.GET.get('page')
    try:
        drugs = paginator.page(page)
    except PageNotAnInteger:
        drugs = paginator.page(1)
    except EmptyPage:
        drugs = paginator.page(paginator.num_pages)

    total_cost_value = drugs_qs.aggregate(
        total=Sum(ExpressionWrapper(
            F('cost_price') * F('stock_quantity') / F('pack_size'),
            output_field=DecimalField(max_digits=15, decimal_places=2)
        ))
    )['total'] or 0

    total_selling_value = drugs_qs.aggregate(
        total=Sum(F('selling_price') * F('stock_quantity'))
    )['total'] or 0

    context = {
        'drugs': drugs,
        'categories': categories,
        'search_query': search_query,
        'selected_category': category_id,
        'total_cost_value': total_cost_value,
        'total_selling_value': total_selling_value,
    }
    return render(request, 'stock/drug_list.html', context)


@login_required
def expired_drug_list(request):
    """List expired drugs with pagination."""
    today = timezone.now().date()
    expired_qs = Drug.objects.filter(expiry_date__lt=today).order_by('expiry_date')

    search_query = request.GET.get('search')
    if search_query:
        expired_qs = expired_qs.filter(
            Q(name__icontains=search_query) |
            Q(generic_name__icontains=search_query) |
            Q(brand__icontains=search_query)
        )

    paginator = Paginator(expired_qs, 10)
    page = request.GET.get('page')
    try:
        expired_drugs = paginator.page(page)
    except PageNotAnInteger:
        expired_drugs = paginator.page(1)
    except EmptyPage:
        expired_drugs = paginator.page(paginator.num_pages)

    context = {
        'expired_drugs': expired_drugs,
        'search_query': search_query,
    }
    return render(request, 'stock/expired_drug_list.html', context)


# ============================================================
# OUT OF STOCK VIEW
# ============================================================

@login_required
def out_of_stock(request):
    """
    View to show drugs that are out of stock (stock_quantity = 0)
    and expired drugs that are no longer available for sale.
    """
    out_of_stock_drugs = Drug.objects.filter(stock_quantity=0).order_by('name')

    today = timezone.now().date()
    expired_with_stock = Drug.objects.filter(
        expiry_date__lt=today,
        stock_quantity__gt=0
    ).order_by('expiry_date')

    expired_out_of_stock = Drug.objects.filter(
        expiry_date__lt=today,
        stock_quantity=0
    ).order_by('expiry_date')

    low_stock_drugs = Drug.objects.filter(
        stock_quantity__gt=0,
        stock_quantity__lte=5
    ).order_by('stock_quantity')

    total_out_of_stock = out_of_stock_drugs.count() + expired_out_of_stock.count()
    has_critical = total_out_of_stock > 0 or expired_with_stock.exists()

    context = {
        'out_of_stock_drugs': out_of_stock_drugs,
        'expired_with_stock': expired_with_stock,
        'expired_out_of_stock': expired_out_of_stock,
        'low_stock_drugs': low_stock_drugs,
        'total_out_of_stock': total_out_of_stock,
        'has_critical': has_critical,
        'today': today,
    }

    return render(request, 'stock/out_of_stock.html', context)


# ============================================================
# DRUG CREATE
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_create(request):
    """Create a new drug/medicine and link to an invoice."""
    categories = Category.objects.all()
    invoices = Invoice.objects.all().select_related('supplier')

    if request.method == 'POST':
        try:
            generic_name = request.POST.get('generic_name')
            dosage = request.POST.get('dosage')
            pack_size = int(request.POST.get('pack_size', 1))
            cost_price = float(request.POST.get('cost_price', 0))
            expiry_date = request.POST.get('expiry_date')
            brand = request.POST.get('brand', '')
            strength = request.POST.get('strength', '')
            batch_no = request.POST.get('batch_no', '')
            stock_quantity = int(request.POST.get('stock_quantity', 0))
            selling_price = float(request.POST.get('selling_price', 0))
            category_id = request.POST.get('category', 1)
            reorder_level = int(request.POST.get('reorder_level', 10))
            invoice_id = request.POST.get('invoice_id')

            errors = []
            if not generic_name:
                errors.append('Generic Name is required.')
            if not dosage:
                errors.append('Dosage is required.')
            if cost_price <= 0:
                errors.append('Cost Price must be greater than 0.')
            if pack_size <= 0:
                errors.append('Pack Size must be greater than 0.')
            if stock_quantity < 0:
                errors.append('Number of packets cannot be negative.')
            if not expiry_date:
                errors.append('Expiry Date is required.')
            if not invoice_id:
                errors.append('Invoice is required.')

            if expiry_date and '/' in expiry_date:
                parts = expiry_date.split('/')
                if len(parts) == 3:
                    expiry_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                else:
                    errors.append('Invalid date format. Use dd/mm/yyyy')

            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                errors.append('Selected category does not exist.')
                category = None

            try:
                invoice = Invoice.objects.get(id=invoice_id)
            except Invoice.DoesNotExist:
                errors.append('Selected invoice does not exist.')
                invoice = None

            if errors:
                for error in errors:
                    messages.error(request, error)
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'invoices': invoices,
                    'is_edit': False,
                    'drug': None,
                    'selected_invoice_id': invoice_id,
                })

            drug = Drug.objects.create(
                name=generic_name,
                generic_name=generic_name,
                brand=brand,
                dosage=dosage,
                strength=strength,
                batch_no=batch_no,
                pack_size=pack_size,
                cost_price=cost_price,
                selling_price=selling_price,
                stock_quantity=stock_quantity * pack_size,
                expiry_date=expiry_date,
                reorder_level=reorder_level,
                category=category,
                created_by=request.user
            )

            InvoiceItem.objects.create(
                invoice=invoice,
                drug=drug,
                quantity=stock_quantity,
                unit_price=cost_price,
                total=cost_price * stock_quantity
            )

            invoice.total_items = invoice.items.count()
            invoice.total_amount = invoice.items.aggregate(Sum('total'))['total__sum'] or 0
            invoice.save()

            messages.success(request, f'Drug "{drug.name}" created and linked to Invoice #{invoice.invoice_number}.')
            return redirect('stock:drug_list')

        except ValueError as e:
            messages.error(request, f'Please enter valid numbers for numeric fields.')
        except Exception as e:
            messages.error(request, f'Error creating drug: {str(e)}')
            import traceback
            traceback.print_exc()

    context = {
        'categories': categories,
        'invoices': invoices,
        'is_edit': False,
        'drug': None,
        'selected_invoice_id': None,
    }
    return render(request, 'stock/drug_form.html', context)


# ============================================================
# DOSAGE FORM VIEWS
# ============================================================

@login_required
def add_dosage_form(request):
    """API endpoint to add a new dosage form"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()

        if not name:
            return JsonResponse({'success': False, 'error': 'Dosage name is required'})

        if len(name) < 2:
            return JsonResponse({'success': False, 'error': 'Name must be at least 2 characters'})

        from .models import Drug
        existing_choices = dict(Drug.DOSAGE_CHOICES)

        from django.core.cache import cache
        custom_choices = cache.get('custom_dosage_forms', {})

        if name in custom_choices:
            return JsonResponse({'success': False, 'error': f'"{name}" already exists as a custom dosage form'})

        if name in existing_choices:
            return JsonResponse({'success': False, 'error': f'"{name}" already exists as a standard dosage form'})

        custom_choices[name] = name.title()
        cache.set('custom_dosage_forms', custom_choices, timeout=None)

        return JsonResponse({
            'success': True,
            'message': f'Dosage form "{name.title()}" added successfully!',
            'added': name
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def get_dosage_forms_api(request):
    """API endpoint to get all dosage forms (standard + custom)"""
    try:
        from .models import Drug
        from django.core.cache import cache

        standard_choices = [{'value': key, 'label': label} for key, label in Drug.DOSAGE_CHOICES]

        custom_choices = cache.get('custom_dosage_forms', {})
        custom_list = [{'value': key, 'label': label} for key, label in custom_choices.items()]

        return JsonResponse({
            'success': True,
            'standard': standard_choices,
            'custom': custom_list,
            'all': standard_choices + custom_list
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================
# DRUG CREATE AJAX
# ============================================================

@login_required
@require_POST
def drug_create_ajax(request):
    """AJAX endpoint to create a new drug from the invoice form modal."""
    try:
        name = request.POST.get('name', '').strip()
        generic_name = request.POST.get('generic_name', '').strip()
        dosage = request.POST.get('dosage', '').strip()
        strength = request.POST.get('strength', '').strip()
        batch_no = request.POST.get('batch_no', '').strip()
        supplier_id = request.POST.get('supplier_id')
        category_id = request.POST.get('category_id')
        expiry_date = request.POST.get('expiry_date')

        try:
            cost_price = Decimal(str(request.POST.get('cost_price', 0)))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid cost price format.'})

        try:
            selling_price = Decimal(str(request.POST.get('selling_price', 0)))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid selling price format.'})

        try:
            pack_size = int(request.POST.get('pack_size', 1))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid pack size format.'})

        try:
            packets = int(request.POST.get('packets', 1))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid packets format.'})

        total_quantity = packets * pack_size

        errors = []

        if not name:
            errors.append('Drug name is required.')
        elif len(name) < 2:
            errors.append('Drug name must be at least 2 characters.')

        if not dosage:
            errors.append('Dosage is required.')

        if cost_price <= 0:
            errors.append('Cost price must be greater than 0.')

        if not category_id:
            errors.append('Category is required.')
        else:
            try:
                from .models import Category
                Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                errors.append('Selected category does not exist.')

        if pack_size <= 0:
            errors.append('Pack size must be greater than 0.')

        if packets <= 0:
            errors.append('Number of packets must be greater than 0.')

        if not expiry_date:
            errors.append('Expiry date is required.')
        else:
            today = timezone.now().date()
            try:
                exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
                if exp_date < today:
                    errors.append('Expiry date cannot be in the past.')
            except ValueError:
                errors.append('Invalid expiry date format. Use YYYY-MM-DD.')

        if errors:
            return JsonResponse({
                'success': False,
                'error': errors[0],
                'errors': errors
            }, status=400)

        if selling_price <= 0:
            selling_price = cost_price * Decimal('1.5')

        from .models import Drug
        drug = Drug.objects.create(
            name=name,
            generic_name=generic_name,
            dosage=dosage,
            strength=strength,
            cost_price=cost_price,
            selling_price=selling_price,
            pack_size=pack_size,
            stock_quantity=total_quantity,
            supplier_id=supplier_id if supplier_id else None,
            category_id=category_id,
            expiry_date=expiry_date,
            batch_no=batch_no,
            created_by=request.user
        )

        return JsonResponse({
            'success': True,
            'drug_id': drug.id,
            'drug_name': drug.name,
            'stock_quantity': drug.stock_quantity,
            'pack_size': drug.pack_size,
            'selling_price': float(drug.selling_price),
            'cost_price': float(drug.cost_price),
        })

    except Exception as e:
        logger.exception("Error creating drug via AJAX")
        return JsonResponse({
            'success': False,
            'error': f'Error creating drug: {str(e)}'
        }, status=500)


# ============================================================
# DRUG EDIT
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_edit(request, drug_id):
    """Edit an existing drug/medicine and optionally update invoice association."""
    drug = get_object_or_404(Drug, id=drug_id)
    categories = Category.objects.all()
    invoices = Invoice.objects.all().select_related('supplier')

    current_invoice_item = InvoiceItem.objects.filter(drug=drug).first()
    current_invoice_id = current_invoice_item.invoice.id if current_invoice_item else None

    if request.method == 'POST':
        try:
            generic_name = request.POST.get('generic_name')
            dosage = request.POST.get('dosage')
            pack_size = int(request.POST.get('pack_size', 1))
            cost_price = float(request.POST.get('cost_price', 0))
            expiry_date = request.POST.get('expiry_date')
            brand = request.POST.get('brand', '')
            strength = request.POST.get('strength', '')
            batch_no = request.POST.get('batch_no', '')
            stock_quantity = int(request.POST.get('stock_quantity', 0))
            selling_price = float(request.POST.get('selling_price', 0))
            category_id = request.POST.get('category', 1)
            reorder_level = int(request.POST.get('reorder_level', 10))
            invoice_id = request.POST.get('invoice_id')

            errors = []
            if not generic_name:
                errors.append('Generic Name is required.')
            if not dosage:
                errors.append('Dosage is required.')
            if cost_price <= 0:
                errors.append('Cost Price must be greater than 0.')
            if pack_size <= 0:
                errors.append('Pack Size must be greater than 0.')
            if stock_quantity < 0:
                errors.append('Number of packets cannot be negative.')
            if not expiry_date:
                errors.append('Expiry Date is required.')
            if not invoice_id:
                errors.append('Invoice is required.')

            if expiry_date and '/' in expiry_date:
                parts = expiry_date.split('/')
                if len(parts) == 3:
                    expiry_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                else:
                    errors.append('Invalid date format. Use dd/mm/yyyy')

            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                errors.append('Selected category does not exist.')
                category = None

            try:
                invoice = Invoice.objects.get(id=invoice_id)
            except Invoice.DoesNotExist:
                errors.append('Selected invoice does not exist.')
                invoice = None

            if errors:
                for error in errors:
                    messages.error(request, error)
                return render(request, 'stock/drug_form.html', {
                    'drug': drug,
                    'categories': categories,
                    'invoices': invoices,
                    'is_edit': True,
                    'selected_invoice_id': invoice_id,
                })

            drug.generic_name = generic_name
            drug.brand = brand
            drug.dosage = dosage
            drug.strength = strength
            drug.batch_no = batch_no
            drug.pack_size = pack_size
            drug.cost_price = cost_price
            drug.selling_price = selling_price
            drug.stock_quantity = stock_quantity * pack_size
            drug.expiry_date = expiry_date
            drug.reorder_level = reorder_level
            drug.category = category
            drug.save()

            if current_invoice_item:
                if current_invoice_item.invoice.id != int(invoice_id):
                    current_invoice_item.delete()
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        drug=drug,
                        quantity=stock_quantity,
                        unit_price=cost_price,
                        total=cost_price * stock_quantity
                    )
                else:
                    current_invoice_item.quantity = stock_quantity
                    current_invoice_item.unit_price = cost_price
                    current_invoice_item.total = cost_price * stock_quantity
                    current_invoice_item.save()
            else:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    drug=drug,
                    quantity=stock_quantity,
                    unit_price=cost_price,
                    total=cost_price * stock_quantity
                )

            if current_invoice_item and current_invoice_item.invoice.id != int(invoice_id):
                old_inv = current_invoice_item.invoice
                old_inv.total_items = old_inv.items.count()
                old_inv.total_amount = old_inv.items.aggregate(Sum('total'))['total__sum'] or 0
                old_inv.save()

            invoice.total_items = invoice.items.count()
            invoice.total_amount = invoice.items.aggregate(Sum('total'))['total__sum'] or 0
            invoice.save()

            messages.success(request, f'Drug "{drug.name}" updated successfully.')
            return redirect('stock:drug_list')

        except ValueError as e:
            messages.error(request, f'Please enter valid numbers for numeric fields.')
        except Exception as e:
            messages.error(request, f'Error updating drug: {str(e)}')
            import traceback
            traceback.print_exc()

    context = {
        'drug': drug,
        'categories': categories,
        'invoices': invoices,
        'is_edit': True,
        'selected_invoice_id': current_invoice_id,
    }
    return render(request, 'stock/drug_form.html', context)


# ============================================================
# DRUG DELETE
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_delete(request, drug_id):
    """Delete a drug and all its related records, updating invoice totals."""
    drug = get_object_or_404(Drug, id=drug_id)

    if request.method == 'POST':
        try:
            from django.db.models import Sum

            invoice_items = InvoiceItem.objects.filter(drug=drug)
            invoices_to_update = set()
            for item in invoice_items:
                invoices_to_update.add(item.invoice)
                item.delete()

            for invoice in invoices_to_update:
                invoice.total_amount = invoice.items.aggregate(Sum('total'))['total__sum'] or 0
                invoice.total_items = invoice.items.count()
                invoice.save()

            SaleItem.objects.filter(drug=drug).delete()
            StockMovement.objects.filter(drug=drug).delete()
            PatientMedication.objects.filter(drug=drug).delete()
            ReturnedDrug.objects.filter(drug=drug).delete()

            drug_name = drug.name
            drug.delete()

            messages.success(request, f'Drug "{drug_name}" and all related records deleted successfully!')
            return redirect('stock:drug_list')

        except Exception as e:
            messages.error(request, f'Error deleting drug: {str(e)}')
            import traceback
            traceback.print_exc()
            return redirect('stock:drug_list')

    return render(request, 'stock/drug_confirm_delete.html', {'drug': drug})


# ============================================================
# ADD STOCK TO DRUG
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def add_stock_to_drug(request):
    """Add stock to an existing drug, linked to an invoice."""
    drugs = Drug.objects.all().order_by('name')
    invoices = Invoice.objects.all().order_by('-invoice_date')
    selected_drug = None

    drug_id = request.GET.get('drug_id')
    if drug_id:
        try:
            selected_drug = Drug.objects.get(id=drug_id)
        except Drug.DoesNotExist:
            pass

    if request.method == 'POST':
        drug_id = request.POST.get('drug_id')
        invoice_id = request.POST.get('invoice_id')
        quantity = int(request.POST.get('quantity', 0))
        cost_price = float(request.POST.get('cost_price', 0))
        selling_price = float(request.POST.get('selling_price', 0))
        batch_no = request.POST.get('batch_no', '')
        expiry_date = request.POST.get('expiry_date')
        pack_size = int(request.POST.get('pack_size', 1))

        if not drug_id or not invoice_id or quantity <= 0:
            messages.error(request, 'Please fill all required fields.')
            return render(request, 'stock/add_stock_to_drug.html', {
                'drugs': drugs,
                'invoices': invoices,
                'selected_drug': selected_drug,
            })

        drug = get_object_or_404(Drug, id=drug_id)
        invoice = get_object_or_404(Invoice, id=invoice_id)

        total_units = quantity * pack_size
        drug.stock_quantity += total_units

        if cost_price > 0:
            drug.cost_price = cost_price
        if selling_price > 0:
            drug.selling_price = selling_price
        if batch_no:
            drug.batch_no = batch_no
        if expiry_date:
            drug.expiry_date = expiry_date
        if pack_size:
            drug.pack_size = pack_size
        drug.save()

        InvoiceItem.objects.create(
            invoice=invoice,
            drug=drug,
            quantity=quantity,
            unit_price=cost_price,
            total=quantity * cost_price
        )

        invoice.total_amount = invoice.items.aggregate(Sum('total'))['total__sum'] or 0
        invoice.save()

        messages.success(request, f'Added {quantity} packets ({total_units} units) of "{drug.name}" to stock via Invoice #{invoice.invoice_number}.')
        return redirect('stock:drug_list')

    context = {
        'drugs': drugs,
        'invoices': invoices,
        'selected_drug': selected_drug,
    }
    return render(request, 'stock/add_stock_to_drug.html', context)


# ============================================================
# SUPPLIER VIEWS
# ============================================================

@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all()
    return render(request, 'stock/supplier_list.html', {'suppliers': suppliers})


@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.created_by = request.user
            supplier.save()
            messages.success(request, f'Supplier "{supplier.name}" created successfully!')
            return redirect('stock:supplier_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SupplierForm()
    return render(request, 'stock/supplier_form.html', {'form': form})


@login_required
def supplier_edit(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, f'Supplier "{supplier.name}" updated successfully!')
            return redirect('stock:supplier_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'stock/supplier_form.html', {'form': form, 'supplier': supplier})


@login_required
def supplier_delete(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id)

    if request.method == 'POST':
        try:
            supplier_name = supplier.name
            supplier.delete()
            messages.success(request, f'Supplier "{supplier_name}" deleted successfully!')
            return redirect('stock:supplier_list')

        except Exception as e:
            messages.error(request, f'Error deleting supplier: {str(e)}')

    return render(request, 'stock/supplier_confirm_delete.html', {'supplier': supplier})


# ============================================================
# RECEIPT/SALES VIEWS
# ============================================================

@login_required
def receipt_list(request):
    receipts = Receipt.objects.all().select_related('created_by').order_by('-created_at')

    today = timezone.now().date()
    today_receipts = Receipt.objects.filter(created_at__date=today)
    today_total = today_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_receipts = Receipt.objects.filter(created_at__gte=month_start)
    month_total = month_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    context = {
        'receipts': receipts,
        'today_total': today_total,
        'month_total': month_total,
        'receipt_count': receipts.count(),
        'today_count': today_receipts.count(),
    }
    return render(request, 'stock/receipt_list.html', context)


@login_required
def receipt_detail(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id)
    return render(request, 'stock/receipt_detail.html', {'receipt': receipt})


# ============================================================
# create_sale_receipt - FIXED with clear_cart signal
# ============================================================

@login_required
def create_sale_receipt(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            items = data.get('items', [])
            customer_name = data.get('customer_name', 'Walk-in Customer')
            customer_phone = data.get('customer_phone', '')
            amount_paid = float(data.get('amount_paid', 0))
            payment_method = data.get('payment_method', 'cash')

            if not items:
                return JsonResponse({'success': False, 'message': 'No items in sale'}, status=400)

            total_amount = 0
            sale_items = []

            for item in items:
                drug_id = item.get('drug_id')
                quantity = int(item.get('quantity', 0))
                selling_price = float(item.get('selling_price', 0))

                if quantity <= 0:
                    continue

                drug = Drug.objects.get(id=drug_id)

                if drug.stock_quantity < quantity:
                    return JsonResponse({
                        'success': False,
                        'message': f'Insufficient stock for {drug.name}. Available: {drug.stock_quantity}'
                    }, status=400)

                drug.stock_quantity -= quantity
                drug.save()

                total = quantity * selling_price
                total_amount += total

                sale_items.append({
                    'drug_name': drug.name,
                    'quantity': quantity,
                    'unit_price': float(selling_price),
                    'total': total
                })

            change_due = amount_paid - total_amount if amount_paid > total_amount else 0

            # CREATE RECEIPT
            receipt = Receipt.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                total_amount=total_amount,
                amount_paid=amount_paid,
                change_due=change_due,
                payment_method=payment_method,
                items=sale_items,
                created_by=request.user
            )

            # CREATE CREDIT SALE IF PAYMENT METHOD IS CREDIT
            if payment_method.lower() == 'credit':
                credit_amount_paid = amount_paid if amount_paid > 0 else 0

                credit_sale = CreditSale.objects.create(
                    credit_receipt_number=f"CR-{timezone.now().strftime('%Y%m%d')}-{CreditSale.objects.filter(created_at__date=timezone.now().date()).count() + 1:04d}",
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    total_amount=total_amount,
                    amount_paid=credit_amount_paid,
                    remaining_balance=total_amount - credit_amount_paid,
                    payment_method='credit',
                    items=sale_items,
                    due_date=timezone.now().date() + timedelta(days=30),
                    status=(
                        'paid' if credit_amount_paid >= total_amount
                        else 'partial' if credit_amount_paid > 0
                        else 'pending'
                    ),
                    created_by=request.user
                )

                receipt.credit_sale = credit_sale
                receipt.is_credit = True
                receipt.save()

                if credit_amount_paid > 0:
                    CreditPayment.objects.create(
                        credit_sale=credit_sale,
                        amount=credit_amount_paid,
                        payment_method=payment_method,
                        reference=f"Initial payment - {payment_method}",
                        created_by=request.user
                    )

                print(f"✅ Created CreditSale: {credit_sale.credit_receipt_number} for receipt {receipt.receipt_number}")

                return JsonResponse({
                    'success': True,
                    'message': 'Credit sale completed successfully!',
                    'receipt_id': receipt.id,
                    'receipt_number': receipt.receipt_number,
                    'total_amount': total_amount,
                    'change_due': change_due,
                    'receipt_url': f'/receipts/{receipt.id}/',
                    'clear_cart': True  # Signal to clear the cart
                })

            return JsonResponse({
                'success': True,
                'message': 'Sale completed successfully!',
                'receipt_id': receipt.id,
                'receipt_number': receipt.receipt_number,
                'total_amount': total_amount,
                'change_due': change_due,
                'receipt_url': f'/receipts/{receipt.id}/',
                'clear_cart': True  # Signal to clear the cart
            })

        except Drug.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Drug not found'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)

    drugs = Drug.objects.filter(stock_quantity__gt=0).order_by('name')
    return render(request, 'stock/sale_form.html', {'drugs': drugs})


@login_required
def print_receipt(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id)

    if not receipt.is_printed:
        receipt.is_printed = True
        receipt.printed_at = timezone.now()
        receipt.save()

    return render(request, 'stock/receipt_print.html', {'receipt': receipt})


@login_required
def get_daily_sales_api(request):
    try:
        today = timezone.now().date()
        receipts = Receipt.objects.filter(created_at__date=today)

        total_sales = receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_transactions = receipts.count()

        last_receipts = receipts.order_by('-created_at')[:10]

        data = []
        for receipt in last_receipts:
            data.append({
                'id': receipt.id,
                'receipt_number': receipt.receipt_number,
                'customer': receipt.customer_name or 'Walk-in',
                'amount': float(receipt.total_amount),
                'time': receipt.created_at.strftime('%H:%M'),
            })

        return JsonResponse({
            'success': True,
            'total_sales': float(total_sales),
            'total_transactions': total_transactions,
            'recent_receipts': data
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ============================================================
# RETURN VIEWS
# ============================================================

@login_required
def return_list(request):
    returns = ReturnedDrug.objects.all().select_related('receipt', 'drug', 'created_by').order_by('-returned_date')
    return render(request, 'stock/return_list.html', {'returns': returns})


@login_required
@permission_required("stock.add_returneddrug", raise_exception=True)
def return_create(request):
    """Create a new return - supports multiple items from one receipt."""
    if request.method == 'POST':
        try:
            receipt_id = request.POST.get('receipt')
            if not receipt_id:
                messages.error(request, 'Please select a receipt.')
                return redirect('stock:return_create')

            drug_ids = request.POST.getlist('drug_ids[]')
            quantities = request.POST.getlist('quantities[]')
            reasons = request.POST.getlist('reasons[]')

            if not (len(drug_ids) == len(quantities) == len(reasons)):
                messages.error(request, 'Invalid submitted data.')
                return redirect('stock:return_create')

            if not drug_ids or not quantities:
                messages.error(request, 'No items selected for return.')
                return redirect('stock:return_create')

            with transaction.atomic():
                try:
                    receipt = Receipt.objects.select_for_update().get(id=receipt_id)
                except Receipt.DoesNotExist:
                    messages.error(request, 'Receipt not found.')
                    return redirect('stock:return_create')

                receipt_lookup = {}

                logger.info(f"Receipt {receipt.receipt_number} items: {receipt.items}")

                for item in receipt.items or []:
                    drug_id = None
                    drug_name = None

                    if 'drug_id' in item:
                        drug_id = item['drug_id']
                    elif 'id' in item:
                        drug_id = item['id']
                    elif 'drugId' in item:
                        drug_id = item['drugId']

                    if 'drug_name' in item:
                        drug_name = item['drug_name']
                    elif 'name' in item:
                        drug_name = item['name']
                    elif 'drugName' in item:
                        drug_name = item['drugName']

                    if drug_id is not None:
                        try:
                            receipt_lookup[int(drug_id)] = item
                            receipt_lookup[str(drug_id)] = item
                        except (ValueError, TypeError):
                            pass

                    if drug_name:
                        receipt_lookup[drug_name] = item
                        receipt_lookup[drug_name.lower()] = item

                returned_count = 0
                failed_items = []

                for drug_id_str, quantity_str, reason in zip(drug_ids, quantities, reasons):
                    try:
                        drug_id = int(drug_id_str)
                        quantity = int(quantity_str)
                    except (ValueError, TypeError):
                        failed_items.append(f'Invalid drug ID or quantity: {drug_id_str}')
                        continue

                    if quantity <= 0:
                        continue

                    try:
                        drug = Drug.objects.select_for_update().get(id=drug_id)
                    except Drug.DoesNotExist:
                        failed_items.append(f'Drug with ID {drug_id} no longer exists.')
                        continue

                    receipt_item = None

                    if drug.id in receipt_lookup:
                        receipt_item = receipt_lookup[drug.id]
                    elif str(drug.id) in receipt_lookup:
                        receipt_item = receipt_lookup[str(drug.id)]
                    elif drug.name in receipt_lookup:
                        receipt_item = receipt_lookup[drug.name]
                    elif drug.name.lower() in receipt_lookup:
                        receipt_item = receipt_lookup[drug.name.lower()]

                    if not receipt_item:
                        failed_items.append(f'"{drug.name}" is not on the selected receipt.')
                        continue

                    try:
                        sold_quantity = (
                            receipt_item.get('quantity') or
                            receipt_item.get('qty') or
                            receipt_item.get('Qty') or
                            0
                        )
                        sold_quantity = int(sold_quantity)
                    except (TypeError, ValueError):
                        sold_quantity = 0

                    if quantity > sold_quantity:
                        failed_items.append(
                            f'You cannot return {quantity} of "{drug.name}". Only {sold_quantity} were sold.'
                        )
                        continue

                    already_returned = ReturnedDrug.objects.filter(
                        receipt=receipt,
                        drug=drug
                    ).aggregate(
                        total=Sum('quantity')
                    )['total'] or 0

                    remaining = max(sold_quantity - already_returned, 0)

                    if quantity > remaining:
                        failed_items.append(
                            f'Only {remaining} of "{drug.name}" can still be returned. '
                            f'({already_returned} already returned)'
                        )
                        continue

                    unit_price = (
                        receipt_item.get('unit_price') or
                        receipt_item.get('price') or
                        receipt_item.get('Price') or
                        drug.selling_price
                    )
                    try:
                        unit_price = Decimal(str(unit_price))
                    except (ValueError, TypeError):
                        unit_price = Decimal('0.00')

                    ReturnedDrug.objects.create(
                        receipt=receipt,
                        drug=drug,
                        quantity=quantity,
                        unit_price=unit_price,
                        reason=reason or 'Return from receipt',
                        created_by=request.user
                    )

                    Drug.objects.filter(id=drug.id).update(
                        stock_quantity=F('stock_quantity') + quantity
                    )

                    StockMovement.objects.create(
                        drug=drug,
                        quantity=quantity,
                        movement_type='return',
                        reference=f"Return from Receipt {receipt.receipt_number}",
                        notes=reason or 'Return from receipt',
                        created_by=request.user
                    )

                    returned_count += 1

                if returned_count > 0:
                    messages.success(
                        request,
                        f'✅ Successfully returned {returned_count} item(s) from "{receipt.receipt_number}" to stock.'
                    )

                if failed_items:
                    if len(failed_items) <= 5:
                        for fail_msg in failed_items:
                            messages.warning(request, f'⚠️ {fail_msg}')
                    else:
                        messages.warning(
                            request,
                            f'⚠️ {len(failed_items)} items could not be returned. '
                            f'Please check the form and try again.'
                        )

            return redirect('stock:return_list')

        except Exception as e:
            logger.exception("Error creating return")
            messages.error(request, f'Error creating return: {str(e)}')
            return redirect('stock:return_create')

    # GET request - show form with properly JSON-encoded items
    import json
    receipts = Receipt.objects.all().order_by('-created_at')

    formatted_receipts = []

    for receipt in receipts:
        items = receipt.items if isinstance(receipt.items, list) else []

        clean_items = []

        for item in items:
            if not item:
                continue

            clean_items.append({
                'drug_id': item.get('drug_id', item.get('id', 0)),
                'drug_name': item.get('drug_name', item.get('name', 'Unknown')),
                'quantity': item.get('quantity', item.get('qty', 0)),
                'unit_price': float(
                    item.get('unit_price', item.get('price', 0)) or 0
                ),
                'total': float(
                    item.get('total', item.get('Total', 0)) or 0
                ),
            })

        formatted_receipts.append({
            'id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'created_at': receipt.created_at,
            'total_amount': float(receipt.total_amount or 0),
            'items': clean_items,
            'items_json': json.dumps(clean_items),
            'item_count': len(clean_items),
        })

    context = {
        'receipts': formatted_receipts,
        'drugs': Drug.objects.all().order_by('name'),
    }

    return render(request, 'stock/return_form.html', context)


@login_required
def get_receipt_items(request, receipt_id):
    """AJAX endpoint to get items for a specific receipt."""
    try:
        receipt = get_object_or_404(Receipt, id=receipt_id)
        items = receipt.items if isinstance(receipt.items, list) else []

        clean_items = []
        for item in items:
            drug_id = (
                item.get('drug_id') or
                item.get('id') or
                item.get('drugId') or
                0
            )
            try:
                drug_id = int(drug_id)
            except (ValueError, TypeError):
                drug_id = 0

            drug_name = (
                item.get('drug_name') or
                item.get('name') or
                item.get('drugName') or
                'Unknown'
            )

            quantity = (
                item.get('quantity') or
                item.get('qty') or
                item.get('Qty') or
                0
            )
            try:
                quantity = int(quantity)
            except (ValueError, TypeError):
                quantity = 0

            unit_price = (
                item.get('unit_price') or
                item.get('price') or
                item.get('Price') or
                0
            )
            try:
                unit_price = float(unit_price)
            except (ValueError, TypeError):
                unit_price = 0

            total = (
                item.get('total') or
                item.get('Total') or
                quantity * unit_price
            )
            try:
                total = float(total)
            except (ValueError, TypeError):
                total = quantity * unit_price

            clean_items.append({
                'drug_id': drug_id,
                'drug_name': drug_name,
                'quantity': quantity,
                'unit_price': unit_price,
                'total': total,
            })

        return JsonResponse({
            'success': True,
            'items': clean_items,
            'receipt_number': receipt.receipt_number,
        })
    except Exception as e:
        logger.exception(f"Error fetching receipt items for {receipt_id}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============================================================
# REPORT VIEWS
# ============================================================

@login_required
def reports_dashboard(request):
    """Main reports dashboard with today, yesterday, weekly, monthly, annual"""
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    daily_receipts = Receipt.objects.filter(created_at__date=today)
    daily_total = daily_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    daily_count = daily_receipts.count()

    yesterday_receipts = Receipt.objects.filter(created_at__date=yesterday)
    yesterday_total = yesterday_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    yesterday_count = yesterday_receipts.count()

    weekly_receipts = Receipt.objects.filter(created_at__date__gte=week_start, created_at__date__lte=today)
    weekly_total = weekly_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    weekly_count = weekly_receipts.count()

    monthly_receipts = Receipt.objects.filter(created_at__date__gte=month_start, created_at__date__lte=today)
    monthly_total = monthly_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    monthly_count = monthly_receipts.count()

    annual_receipts = Receipt.objects.filter(created_at__date__gte=year_start, created_at__date__lte=today)
    annual_total = annual_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    annual_count = annual_receipts.count()

    recent_receipts = Receipt.objects.all().order_by('-created_at')[:20]
    recent_invoices = Invoice.objects.all().order_by('-created_at')[:10]

    payment_breakdown = daily_receipts.values('payment_method').annotate(
        total=Sum('total_amount'),
        count=Count('id')
    )

    top_drugs = []
    for receipt in Receipt.objects.all()[:100]:
        if receipt.items:
            for item in receipt.items:
                top_drugs.append({
                    'name': item.get('drug_name', 'Unknown'),
                    'quantity': item.get('quantity', 0),
                    'total': item.get('total', 0)
                })

    drug_summary = {}
    for drug in top_drugs:
        name = drug['name']
        if name in drug_summary:
            drug_summary[name]['quantity'] += drug['quantity']
            drug_summary[name]['total'] += drug['total']
        else:
            drug_summary[name] = {'quantity': drug['quantity'], 'total': drug['total']}

    top_selling = sorted(drug_summary.items(), key=lambda x: x[1]['quantity'], reverse=True)[:10]

    # Credit sales statistics
    total_outstanding = CreditSale.objects.filter(
        status__in=['pending', 'partial']
    ).aggregate(
        total=Sum('remaining_balance')
    )['total'] or Decimal("0.00")

    overdue_credits = CreditSale.objects.filter(
        status__in=['pending', 'partial'],
        due_date__lt=today
    ).count()

    context = {
        'daily_total': daily_total,
        'daily_count': daily_count,
        'yesterday_total': yesterday_total,
        'yesterday_count': yesterday_count,
        'weekly_total': weekly_total,
        'weekly_count': weekly_count,
        'monthly_total': monthly_total,
        'monthly_count': monthly_count,
        'annual_total': annual_total,
        'annual_count': annual_count,
        'recent_receipts': recent_receipts,
        'recent_invoices': recent_invoices,
        'payment_breakdown': payment_breakdown,
        'top_selling': top_selling,
        'today': today,
        'yesterday': yesterday,
        'week_start': week_start,
        'month_start': month_start,
        'year_start': year_start,
        'total_outstanding': total_outstanding,
        'overdue_credits': overdue_credits,
    }

    return render(request, 'stock/reports_dashboard.html', context)


@login_required
def generate_report_api(request):
    """API to generate and send email report"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=400)

    try:
        data = json.loads(request.body)
        report_type = data.get('report_type', 'daily')
        email = data.get('email', 'kiyimbahenry314@gmail.com')

        today = timezone.now().date()

        if report_type == 'daily':
            report_date = today
        elif report_type == 'weekly':
            report_date = today
        elif report_type == 'monthly':
            report_date = today
        elif report_type == 'annual':
            report_date = today
        else:
            report_date = today

        report_data = generate_report_data(report_type, report_date)

        success = send_report_email(report_data, email, report_type)

        if success:
            report = Report.objects.create(
                report_type=report_type,
                data=report_data,
                generated_by=request.user,
                sent_to_email=True,
                email_sent_at=timezone.now()
            )

            return JsonResponse({
                'success': True,
                'message': f'{report_type.capitalize()} report sent to {email}',
                'report_id': report.id
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Failed to send email. Please check email settings.'
            }, status=500)

    except Exception as e:
        if settings.DEBUG:
            import traceback
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}',
                'traceback': traceback.format_exc()
            }, status=500)
        else:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ============================================================
# generate_report_data
# ============================================================

def generate_report_data(report_type, report_date=None):
    """
    Generate report data based on type (including returns and credit sales)
    """
    if report_date is None:
        report_date = timezone.now().date()

    today = report_date
    yesterday = today - timedelta(days=1)

    report_data = {
        'report_type': report_type,
        'report_date': report_date.isoformat(),
        'generated_at': timezone.localtime().strftime('%Y-%m-%d %H:%M:%S'),
        'sales': {},
        'invoices': {},
        'payment_breakdown': [],
        'top_products': [],
        'credit_sales': {}
    }

    if report_type == 'daily':
        start_date = report_date
        end_date = report_date
        report_data['period'] = f"Daily Report - {report_date.strftime('%B %d, %Y')}"
    elif report_type == 'weekly':
        end_date = report_date
        start_date = end_date - timedelta(days=7)
        report_data['period'] = f"Weekly Report - {start_date.strftime('%B %d')} to {end_date.strftime('%B %d, %Y')}"
    elif report_type == 'monthly':
        end_date = report_date
        start_date = end_date.replace(day=1)
        report_data['period'] = f"Monthly Report - {end_date.strftime('%B %Y')}"
    elif report_type == 'annual':
        end_date = report_date
        start_date = end_date.replace(month=1, day=1)
        report_data['period'] = f"Annual Report - {end_date.year}"
    else:
        start_date = report_date
        end_date = report_date

    receipts = Receipt.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )

    returns = ReturnedDrug.objects.filter(
        returned_date__date__gte=start_date,
        returned_date__date__lte=end_date
    )

    credit_sales = CreditSale.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )

    total_sales = receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_transactions = receipts.count()
    total_items_sold = 0
    for receipt in receipts:
        if receipt.items:
            for item in receipt.items:
                total_items_sold += item.get('quantity', 0)

    total_returned_amount = returns.aggregate(Sum('total_refund'))['total_refund__sum'] or 0
    total_returned_items = returns.aggregate(Sum('quantity'))['quantity__sum'] or 0

    net_sales = total_sales - total_returned_amount

    # Credit sales data
    total_credit_amount = credit_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_credit_paid = credit_sales.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    total_credit_outstanding = total_credit_amount - total_credit_paid

    report_data['sales'] = {
        'total_amount': float(total_sales),
        'net_sales': float(net_sales),
        'total_returns': float(total_returned_amount),
        'total_returned_items': int(total_returned_items),
        'total_transactions': total_transactions,
        'total_items_sold': total_items_sold,
        'average_transaction': float(total_sales / total_transactions) if total_transactions > 0 else 0,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
    }

    report_data['credit_sales'] = {
        'total_credit_amount': float(total_credit_amount),
        'total_credit_paid': float(total_credit_paid),
        'total_credit_outstanding': float(total_credit_outstanding),
        'total_credit_transactions': credit_sales.count(),
        'overdue_count': credit_sales.filter(
            status__in=['pending', 'partial'],
            due_date__lt=timezone.now().date()
        ).count(),
    }

    payment_breakdown = receipts.values('payment_method').annotate(
        total=Sum('total_amount'),
        count=Count('id')
    )

    for item in payment_breakdown:
        report_data['payment_breakdown'].append({
            'method': item['payment_method'] or 'unknown',
            'total': float(item['total']),
            'count': item['count']
        })

    product_sales = {}
    for receipt in receipts:
        if receipt.items:
            for item in receipt.items:
                name = item.get('drug_name', 'Unknown')
                quantity = item.get('quantity', 0)
                total = item.get('total', 0)
                if name in product_sales:
                    product_sales[name]['quantity'] += quantity
                    product_sales[name]['total'] += total
                else:
                    product_sales[name] = {'quantity': quantity, 'total': total}

    sorted_products = sorted(product_sales.items(), key=lambda x: x[1]['quantity'], reverse=True)[:10]
    for name, data in sorted_products:
        report_data['top_products'].append({
            'name': name,
            'quantity': data['quantity'],
            'total': float(data['total'])
        })

    invoices = Invoice.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    report_data['invoices'] = {
        'total_invoices': invoices.count(),
        'total_invoice_value': float(invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0),
        'pending_count': invoices.filter(status='pending').count(),
        'paid_count': invoices.filter(status='paid').count(),
    }

    return report_data


# ============================================================
# INVOICE VIEWS
# ============================================================

@login_required
def invoice_list(request):
    invoices = Invoice.objects.all().select_related('supplier', 'created_by').order_by('-created_at')
    return render(request, 'stock/invoice_list.html', {'invoices': invoices})


@login_required
@user_passes_test(is_admin_or_manager)
def invoice_create(request):
    suppliers = Supplier.objects.all()
    categories = Category.objects.all()
    drugs = Drug.objects.all()

    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.created_by = request.user
            invoice.save()

            drug_ids = request.POST.getlist('drug[]')
            quantities = request.POST.getlist('quantity[]')
            unit_prices = request.POST.getlist('unit_price[]')

            total_amount = 0
            total_items_count = 0
            for i in range(len(drug_ids)):
                drug_id = drug_ids[i]
                quantity = int(quantities[i])
                unit_price = float(unit_prices[i])
                if drug_id and quantity > 0 and unit_price > 0:
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        drug_id=drug_id,
                        quantity=quantity,
                        unit_price=unit_price,
                        total=quantity * unit_price
                    )
                    total_amount += quantity * unit_price
                    total_items_count += 1

            invoice.total_amount = total_amount
            invoice.total_items = total_items_count
            invoice.total_cost = total_amount
            invoice.save()

            messages.success(request, f'Invoice "{invoice.invoice_number}" created successfully!')
            return redirect('stock:invoice_list')
        else:
            print(form.errors)
            messages.error(request, 'Please correct the errors below.')
            return render(request, 'stock/invoice_form.html', {
                'form': form,
                'suppliers': suppliers,
                'drugs': drugs,
                'categories': categories,
            })
    else:
        form = InvoiceForm()

    context = {
        'form': form,
        'suppliers': suppliers,
        'drugs': drugs,
        'categories': categories,
    }
    return render(request, 'stock/invoice_form.html', context)


@login_required
@user_passes_test(is_admin_or_manager)
def invoice_edit(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    suppliers = Supplier.objects.all()
    categories = Category.objects.all()
    drugs = Drug.objects.all()
    existing_items = invoice.items.all()

    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.save()

            invoice.items.all().delete()

            drug_ids = request.POST.getlist('drug[]')
            quantities = request.POST.getlist('quantity[]')
            unit_prices = request.POST.getlist('unit_price[]')

            total_amount = 0
            for i in range(len(drug_ids)):
                drug_id = drug_ids[i]
                quantity = int(quantities[i])
                unit_price = float(unit_prices[i])
                if drug_id and quantity > 0 and unit_price > 0:
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        drug_id=drug_id,
                        quantity=quantity,
                        unit_price=unit_price,
                        total=quantity * unit_price
                    )
                    total_amount += quantity * unit_price

            invoice.total_amount = total_amount
            invoice.save()

            messages.success(request, f'Invoice "{invoice.invoice_number}" updated successfully!')
            return redirect('stock:invoice_list')
        else:
            messages.error(request, 'Please correct the errors below.')
            return render(request, 'stock/invoice_form.html', {
                'form': form,
                'invoice': invoice,
                'suppliers': suppliers,
                'drugs': drugs,
                'categories': categories,
                'items': existing_items,
            })
    else:
        form = InvoiceForm(instance=invoice)

    context = {
        'form': form,
        'invoice': invoice,
        'suppliers': suppliers,
        'drugs': drugs,
        'categories': categories,
        'items': existing_items,
    }
    return render(request, 'stock/invoice_form.html', context)


@login_required
def invoice_detail(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    items = invoice.items.all().select_related('drug')
    return render(request, 'stock/invoice_detail.html', {
        'invoice': invoice,
        'items': items
    })


@login_required
@user_passes_test(is_admin_or_manager)
def invoice_delete(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)

    if request.method == 'POST':
        try:
            for item in invoice.items.all():
                drug = item.drug
                drug.stock_quantity -= item.quantity
                drug.save()

            invoice_number = invoice.invoice_number
            invoice.delete()
            messages.success(request, f'Invoice #{invoice_number} deleted successfully!')
            return redirect('stock:invoice_list')

        except Exception as e:
            messages.error(request, f'Error deleting invoice: {str(e)}')

    return render(request, 'stock/invoice_confirm_delete.html', {'invoice': invoice})


# ============================================================
# CATEGORY VIEWS
# ============================================================

@login_required
def category_list(request):
    categories = Category.objects.all()
    return render(request, 'stock/category_list.html', {'categories': categories})


# ============================================================
# API VIEWS
# ============================================================

@login_required
def calculate_selling_price(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            purchase_price = float(data.get('purchase_price', 0))
            markup_percentage = float(data.get('markup_percentage', 30))

            selling_price = purchase_price * (1 + markup_percentage / 100)

            return JsonResponse({
                'success': True,
                'selling_price': round(selling_price, 2)
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


# ============================================================
# USER MANAGEMENT VIEWS (Admin only)
# ============================================================

def is_admin(user):
    return user.is_superuser


@login_required
@user_passes_test(is_admin_or_manager)
def user_list(request):
    users = User.objects.all()
    return render(request, 'stock/user_list.html', {'users': users})


@login_required
@user_passes_test(is_admin_or_manager)
def user_create(request):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('pharmacist', 'Pharmacist'),
        ('cashier', 'Cashier'),
        ('dispenser', 'Dispenser'),
        ('viewer', 'Viewer (Read-only)'),
    ]

    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            password = request.POST.get('password')
            is_staff = request.POST.get('is_staff') == 'on'
            is_superuser = request.POST.get('is_superuser') == 'on'
            role = request.POST.get('role')

            if User.objects.filter(username=username).exists():
                messages.error(request, 'Username already exists.')
                return render(request, 'stock/user_form.html', {
                    'is_edit': False,
                    'role_choices': ROLE_CHOICES,
                })

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.save()

            if role:
                from django.contrib.auth.models import Group
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.add(group)

            messages.success(request, f'User "{username}" created successfully!')
            return redirect('stock:user_list')

        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')

    return render(request, 'stock/user_form.html', {
        'is_edit': False,
        'role_choices': ROLE_CHOICES,
    })


@login_required
@user_passes_test(is_admin_or_manager)
def user_detail(request, user_id):
    user = get_object_or_404(User, id=user_id)
    return render(request, 'stock/user_detail.html', {'user': user})


@login_required
@user_passes_test(is_admin_or_manager)
def user_edit(request, user_id):
    user = get_object_or_404(User, id=user_id)

    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('pharmacist', 'Pharmacist'),
        ('cashier', 'Cashier'),
        ('dispenser', 'Dispenser'),
        ('viewer', 'Viewer (Read-only)'),
    ]

    current_role = user.groups.first().name if user.groups.exists() else ''

    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name', '')
            last_name = request.POST.get('last_name', '')
            role = request.POST.get('role')
            password = request.POST.get('password1')
            confirm_password = request.POST.get('password2')

            if password and password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return render(request, 'stock/user_form.html', {
                    'is_edit': True,
                    'user': user,
                    'role_choices': ROLE_CHOICES,
                    'user_role': current_role,
                })

            if User.objects.exclude(id=user.id).filter(username=username).exists():
                messages.error(request, 'Username already taken.')
                return render(request, 'stock/user_form.html', {
                    'is_edit': True,
                    'user': user,
                    'role_choices': ROLE_CHOICES,
                    'user_role': current_role,
                })

            user.username = username
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            if password:
                user.set_password(password)
            user.save()

            if role:
                user.groups.clear()
                from django.contrib.auth.models import Group
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.add(group)

            messages.success(request, f'User "{username}" updated successfully!')
            return redirect('stock:user_list')

        except Exception as e:
            messages.error(request, f'Error updating user: {str(e)}')

    return render(request, 'stock/user_form.html', {
        'is_edit': True,
        'user': user,
        'role_choices': ROLE_CHOICES,
        'user_role': current_role,
        'title': 'Edit User',
    })


@login_required
@user_passes_test(is_admin_or_manager)
def user_delete(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        try:
            username = user.username
            user.delete()
            messages.success(request, f'User "{username}" deleted successfully!')
            return redirect('stock:user_list')

        except Exception as e:
            messages.error(request, f'Error deleting user: {str(e)}')

    return render(request, 'stock/user_delete.html', {'user': user})


# ============================================================
# CHRONIC PATIENT VIEWS
# ============================================================

@login_required
def patient_list(request):
    patients = ChronicPatient.objects.all().select_related('created_by')

    search_query = request.GET.get('search')
    if search_query:
        patients = patients.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(patient_id__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(location__icontains=search_query)
        )

    disease_filter = request.GET.get('disease')
    if disease_filter:
        patients = patients.filter(disease_type=disease_filter)

    context = {
        'patients': patients,
        'search_query': search_query,
        'disease_filter': disease_filter,
        'disease_choices': ChronicPatient.DISEASE_CHOICES,
    }
    return render(request, 'stock/patient_list.html', context)


@login_required
def patient_create(request):
    if request.method == 'POST':
        try:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            date_of_birth = request.POST.get('date_of_birth') or None
            gender = request.POST.get('gender', '')
            phone = request.POST.get('phone', '').strip()
            alternate_phone = request.POST.get('alternate_phone', '').strip()
            email = request.POST.get('email', '').strip() or None
            location = request.POST.get('location', '').strip()
            village = request.POST.get('village', '').strip()
            district = request.POST.get('district', '').strip()
            disease_type = request.POST.get('disease_type', '')
            other_disease = request.POST.get('other_disease', '').strip()
            diagnosis_date = request.POST.get('diagnosis_date') or None
            medications = request.POST.get('medications', '').strip()
            dosage = request.POST.get('dosage', '').strip()
            next_appointment = request.POST.get('next_appointment') or None

            errors = []
            if not first_name:
                errors.append('First name is required.')
            if not last_name:
                errors.append('Last name is required.')
            if not disease_type:
                errors.append('Disease type is required.')
            if disease_type == 'OTHER' and not other_disease:
                errors.append('Please specify the disease type.')

            if errors:
                for error in errors:
                    messages.error(request, error)
                return render(request, 'stock/patient_form.html', {
                    'disease_choices': ChronicPatient.DISEASE_CHOICES,
                    'is_edit': False
                })

            patient = ChronicPatient.objects.create(
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
                gender=gender,
                phone=phone,
                alternate_phone=alternate_phone,
                email=email,
                location=location,
                village=village,
                district=district,
                disease_type=disease_type,
                other_disease=other_disease if disease_type == 'OTHER' else '',
                diagnosis_date=diagnosis_date,
                medications=medications,
                dosage=dosage,
                next_appointment=next_appointment,
                created_by=request.user
            )

            messages.success(request, f'Patient "{patient.first_name} {patient.last_name}" registered successfully!')
            return redirect('stock:patient_list')

        except Exception as e:
            messages.error(request, f'Error creating patient: {str(e)}')
            import traceback
            traceback.print_exc()

    context = {
        'disease_choices': ChronicPatient.DISEASE_CHOICES,
        'is_edit': False,
    }
    return render(request, 'stock/patient_form.html', context)


@login_required
def patient_edit(request, patient_id):
    patient = get_object_or_404(ChronicPatient, id=patient_id)

    if request.method == 'POST':
        try:
            patient.first_name = request.POST.get('first_name', '').strip()
            patient.last_name = request.POST.get('last_name', '').strip()
            patient.date_of_birth = request.POST.get('date_of_birth') or None
            patient.gender = request.POST.get('gender', '')
            patient.phone = request.POST.get('phone', '').strip()
            patient.alternate_phone = request.POST.get('alternate_phone', '').strip()
            patient.email = request.POST.get('email', '').strip() or None
            patient.location = request.POST.get('location', '').strip()
            patient.village = request.POST.get('village', '').strip()
            patient.district = request.POST.get('district', '').strip()
            patient.disease_type = request.POST.get('disease_type', '')
            patient.other_disease = request.POST.get('other_disease', '').strip() if patient.disease_type == 'OTHER' else ''
            patient.diagnosis_date = request.POST.get('diagnosis_date') or None
            patient.medications = request.POST.get('medications', '').strip()
            patient.dosage = request.POST.get('dosage', '').strip()
            patient.next_appointment = request.POST.get('next_appointment') or None
            patient.is_active = request.POST.get('is_active') == 'on'

            patient.save()

            messages.success(request, f'Patient "{patient.first_name} {patient.last_name}" updated successfully!')
            return redirect('stock:patient_list')

        except Exception as e:
            messages.error(request, f'Error updating patient: {str(e)}')

    context = {
        'patient': patient,
        'disease_choices': ChronicPatient.DISEASE_CHOICES,
        'is_edit': True,
    }
    return render(request, 'stock/patient_form.html', context)


@login_required
def patient_detail(request, patient_id):
    patient = get_object_or_404(ChronicPatient, id=patient_id)
    return render(request, 'stock/patient_detail.html', {'patient': patient})


@login_required
def patient_delete(request, patient_id):
    patient = get_object_or_404(ChronicPatient, id=patient_id)

    if request.method == 'POST':
        try:
            patient_name = f"{patient.first_name} {patient.last_name}"
            patient.delete()
            messages.success(request, f'Patient "{patient_name}" deleted successfully!')
            return redirect('stock:patient_list')
        except Exception as e:
            messages.error(request, f'Error deleting patient: {str(e)}')

    return render(request, 'stock/patient_confirm_delete.html', {'patient': patient})


@login_required
def patient_add_medication(request, patient_id):
    patient = get_object_or_404(ChronicPatient, id=patient_id)

    if request.method == 'POST':
        try:
            medication_name = request.POST.get('medication_name', '').strip()
            dosage = request.POST.get('dosage', '').strip()
            frequency = request.POST.get('frequency', '').strip()
            duration = request.POST.get('duration', '').strip()
            notes = request.POST.get('notes', '').strip()

            if not medication_name:
                messages.error(request, 'Medication name is required.')
            else:
                PatientMedication.objects.create(
                    patient=patient,
                    medication_name=medication_name,
                    dosage=dosage,
                    frequency=frequency,
                    duration=duration,
                    notes=notes
                )
                messages.success(request, f'Medication "{medication_name}" added successfully!')

        except Exception as e:
            messages.error(request, f'Error adding medication: {str(e)}')

        return redirect('stock:patient_detail', patient_id=patient_id)

    return redirect('stock:patient_detail', patient_id=patient_id)


@login_required
def patient_remove_medication(request, medication_id):
    medication = get_object_or_404(PatientMedication, id=medication_id)
    patient_id = medication.patient.id

    if request.method == 'POST':
        medication.delete()
        messages.success(request, 'Medication removed successfully!')

    return redirect('stock:patient_detail', patient_id=patient_id)


# ============================================================
# HELPER FUNCTION TO CREATE TEST DRUGS
# ============================================================

def create_test_drugs():
    from django.contrib.auth.models import User

    if Drug.objects.count() > 0:
        print(f"✅ {Drug.objects.count()} drugs already exist")
        return

    categories_data = [
        'Antibiotic', 'Anti-hypertensives', 'Anti-diabetics', 'Anti-Ulcer',
        'Cough and Flu', 'Neuro Care', 'Anti-fungals', 'Anti-infectives',
        'Painkillers', 'Beauty and Cosmetics', 'Vitamins and Minerals', 'Supplements'
    ]

    for name in categories_data:
        Category.objects.get_or_create(name=name)

    category = Category.objects.first()

    admin = User.objects.filter(is_superuser=True).first()
    if not admin:
        admin = User.objects.first()

    if not admin:
        print("❌ No user found to assign as creator")
        return

    test_drugs = [
        {'name': 'ibuprofen', 'generic_name': 'ibuprofen', 'selling_price': 4000, 'stock_quantity': 100},
        {'name': 'paracetamol', 'generic_name': 'paracetamol', 'selling_price': 4000, 'stock_quantity': 50},
        {'name': 'amoxicillin', 'generic_name': 'amoxicillin', 'selling_price': 5000, 'stock_quantity': 30},
        {'name': 'metformin', 'generic_name': 'metformin', 'selling_price': 3000, 'stock_quantity': 45},
        {'name': 'amlodipine', 'generic_name': 'amlodipine', 'selling_price': 3500, 'stock_quantity': 25},
    ]

    created_count = 0
    for drug_data in test_drugs:
        drug, created = Drug.objects.get_or_create(
            name=drug_data['name'],
            defaults={
                'generic_name': drug_data.get('generic_name', drug_data['name']),
                'category': category,
                'selling_price': drug_data['selling_price'],
                'cost_price': drug_data['selling_price'] * 0.6,
                'stock_quantity': drug_data['stock_quantity'],
                'reorder_level': 10,
                'pack_size': 1,
                'dosage': 'Standard',
                'created_by': admin
            }
        )
        if created:
            created_count += 1
            print(f"✅ Created drug: {drug.name}")

    print(f"✅ Created {created_count} test drugs")
    print(f"Total drugs now: {Drug.objects.count()}")
