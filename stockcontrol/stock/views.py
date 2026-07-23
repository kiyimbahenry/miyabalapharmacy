from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
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
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.management import call_command
import json
import os
import base64
import traceback
from datetime import datetime, timedelta
from decimal import Decimal

# Brevo / Sendinblue
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

# Your utils
from .utils.invoice_pdf import get_invoices_zip, get_invoices_zip_range
from .utils.report_generator import generate_daily_report_pdf, generate_comprehensive_report_pdf

# ===== IMPORTS =====
from .models import (
    Drug, Supplier, Invoice, Category, InvoiceItem,
    Sale, SaleItem, Receipt, Report, ChronicPatient,
    PatientMedication, PatientVisit,
    ReturnedDrug, StockMovement
)
# ===== FORM IMPORTS =====
from .forms import SupplierForm, InvoiceForm, DrugForm, StockMovementForm


def is_admin_or_manager(user):
    """Return True if user is superuser or belongs to 'admin' or 'manager' group."""
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=['admin', 'manager']).exists()

@csrf_exempt
def run_daily_report(request):
    """Endpoint to trigger daily report via cron-job.org"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        call_command('send_daily_report')
        return JsonResponse({'success': True, 'message': 'Daily report sent successfully'})
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

            # Try to find user by email first
            if '@' in username_or_email:
                try:
                    user_obj = User.objects.get(email=username_or_email)
                    user = authenticate(request, username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass

            # If not found by email, try by username
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
    """Dashboard view showing statistics and recent data"""
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

    context = {
        'total_medicines': total_medicines,
        'total_suppliers': total_suppliers,
        'total_invoices': total_invoices,
        'low_stock_count': low_stock_count,
        'recent_medicines': recent_medicines,
        'total_stock_value': total_stock_value,
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
        ).order_by('name')
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
            })
        return JsonResponse(data, safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================
# NEW AUTOCOMPLETE API – searches across name, brand, generic
# ============================================================

@login_required
def autocomplete_drugs(request):
    """
    API endpoint for drug autocomplete.
    Searches across name, brand, and generic_name.
    Used by the Add Stock form and any other autocomplete inputs.
    """
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
# COMPLETE SALE (unchanged)
# ============================================================

@login_required
def complete_sale(request):
    """
    API endpoint to complete a drug sale and update stock
    Supports multiple data formats for maximum compatibility
    """
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
                'message': 'No items found in request. Expected "items" array, "cart" array, or single item with drug_id/name.',
                'received_data': data,
                'available_keys': list(data.keys())
            }, status=400)

        customer_name = data.get('customer_name', 'Walk-in Customer')
        customer_phone = data.get('customer_phone', '')
        amount_paid = float(data.get('amount_paid', 0))
        payment_method = data.get('payment_method', 'cash')
        sale_type = data.get('sale_type', 'retail')

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

        change_due = amount_paid - total_amount if amount_paid > total_amount else 0

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
            'receipt_url': f'/receipts/{receipt.id}/'
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
# DRUG (MEDICINE) VIEWS
# ============================================================

@login_required
def drug_list(request):
    """List all drugs/medicines with summary totals, exclude expired, paginated."""
    today = timezone.now().date()

    # Base queryset: exclude expired drugs (expiry_date < today) and order by generic_name
    drugs_qs = Drug.objects.filter(
        Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
    ).select_related('category', 'supplier').order_by('generic_name')

    # Filter by category
    category_id = request.GET.get('category')
    if category_id:
        drugs_qs = drugs_qs.filter(category_id=category_id)

    # Search
    search_query = request.GET.get('search')
    if search_query:
        drugs_qs = drugs_qs.filter(
            Q(name__icontains=search_query) |
            Q(generic_name__icontains=search_query) |
            Q(brand__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    categories = Category.objects.all()

    # ---- PAGINATION ----
    paginator = Paginator(drugs_qs, 10)  # 10 per page
    page = request.GET.get('page')
    try:
        drugs = paginator.page(page)
    except PageNotAnInteger:
        drugs = paginator.page(1)
    except EmptyPage:
        drugs = paginator.page(paginator.num_pages)

    # ---- TOTALS (on the filtered queryset, not just the current page) ----
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
        'drugs': drugs,               # paginated object
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

    # Search (optional)
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
# DRUG CREATE - FIXED + RESTRICTED
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_create(request):
    """Create a new drug/medicine and link to an invoice."""
    categories = Category.objects.all()
    invoices = Invoice.objects.all().select_related('supplier')

    if request.method == 'POST':
        try:
            # Get form data
            generic_name = request.POST.get('generic_name')
            dosage = request.POST.get('dosage')
            pack_size = int(request.POST.get('pack_size', 1))
            cost_price = float(request.POST.get('cost_price', 0))
            expiry_date = request.POST.get('expiry_date')
            brand = request.POST.get('brand', '')
            strength = request.POST.get('strength', '')
            batch_no = request.POST.get('batch_no', '')
            stock_quantity = int(request.POST.get('stock_quantity', 0))  # number of packets
            selling_price = float(request.POST.get('selling_price', 0))
            category_id = request.POST.get('category', 1)
            reorder_level = int(request.POST.get('reorder_level', 10))
            invoice_id = request.POST.get('invoice_id')

            # Basic validation
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

            # Convert expiry date format (dd/mm/yyyy → yyyy-mm-dd)
            if expiry_date and '/' in expiry_date:
                parts = expiry_date.split('/')
                if len(parts) == 3:
                    expiry_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                else:
                    errors.append('Invalid date format. Use dd/mm/yyyy')

            # Verify category exists
            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                errors.append('Selected category does not exist.')
                category = None

            # Verify invoice exists
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

            # Create the drug (total tablets = packets × pack_size)
            drug = Drug.objects.create(
                name=generic_name,  # use generic as name if no brand given
                generic_name=generic_name,
                brand=brand,
                dosage=dosage,
                strength=strength,
                batch_no=batch_no,
                pack_size=pack_size,
                cost_price=cost_price,
                selling_price=selling_price,
                stock_quantity=stock_quantity * pack_size,  # total tablets
                expiry_date=expiry_date,
                reorder_level=reorder_level,
                category=category,
                created_by=request.user
            )

            # Create InvoiceItem for this purchase
            # quantity = number of packets, unit_price = cost per packet
            InvoiceItem.objects.create(
                invoice=invoice,
                drug=drug,
                quantity=stock_quantity,                # packets
                unit_price=cost_price,                  # cost per packet
                total=cost_price * stock_quantity       # total cost of this purchase
            )

            # Optionally update the invoice totals
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

    # GET request
    context = {
        'categories': categories,
        'invoices': invoices,
        'is_edit': False,
        'drug': None,
        'selected_invoice_id': None,
    }
    return render(request, 'stock/drug_form.html', context)


# ============================================================
# DRUG CREATE AJAX - FOR INVOICE MODAL (UPDATED)
# ============================================================

@login_required
@require_POST
def drug_create_ajax(request):
    """
    AJAX endpoint to create a new drug from the invoice form modal.
    Validates that the expiry date is not in the past.
    """
    try:
        name = request.POST.get('name')
        generic_name = request.POST.get('generic_name', '')
        dosage = request.POST.get('dosage')
        strength = request.POST.get('strength', '')
        cost_price = float(request.POST.get('cost_price', 0))
        selling_price = float(request.POST.get('selling_price', 0))
        pack_size = int(request.POST.get('pack_size', 1))
        supplier_id = request.POST.get('supplier_id')
        category_id = request.POST.get('category_id')
        expiry_date = request.POST.get('expiry_date')
        batch_no = request.POST.get('batch_no', '')
        packets = int(request.POST.get('packets', 1))

        # Calculate total stock quantity: packets × pack size
        total_quantity = packets * pack_size

        # ---- Validation ----
        if not name:
            return JsonResponse({'success': False, 'error': 'Drug name is required.'})
        if not dosage:
            return JsonResponse({'success': False, 'error': 'Dosage is required.'})
        if cost_price <= 0:
            return JsonResponse({'success': False, 'error': 'Cost price must be greater than 0.'})
        if not category_id:
            return JsonResponse({'success': False, 'error': 'Category is required.'})
        if pack_size <= 0:
            return JsonResponse({'success': False, 'error': 'Pack size must be greater than 0.'})
        if packets <= 0:
            return JsonResponse({'success': False, 'error': 'Number of packets must be greater than 0.'})
        if expiry_date:
            # Check if expiry date is in the past
            today = timezone.now().date()
            try:
                exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
                if exp_date < today:
                    return JsonResponse({'success': False, 'error': 'Expiry date cannot be in the past.'})
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Invalid expiry date format.'})
        else:
            return JsonResponse({'success': False, 'error': 'Expiry date is required.'})

        # Create the drug
        drug = Drug.objects.create(
            name=name,
            generic_name=generic_name,
            dosage=dosage,
            strength=strength,
            cost_price=cost_price,
            selling_price=selling_price if selling_price > 0 else cost_price * 1.5,
            pack_size=pack_size,
            stock_quantity=total_quantity,  # Total = packets × pack_size
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
            'stock_quantity': drug.stock_quantity
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ============================================================
# DRUG EDIT - FIXED + RESTRICTED
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_edit(request, drug_id):
    """Edit an existing drug/medicine and optionally update invoice association."""
    drug = get_object_or_404(Drug, id=drug_id)
    categories = Category.objects.all()
    invoices = Invoice.objects.all().select_related('supplier')

    # Get current invoice linked to this drug (if any)
    current_invoice_item = InvoiceItem.objects.filter(drug=drug).first()
    current_invoice_id = current_invoice_item.invoice.id if current_invoice_item else None

    if request.method == 'POST':
        try:
            # Get form data
            generic_name = request.POST.get('generic_name')
            dosage = request.POST.get('dosage')
            pack_size = int(request.POST.get('pack_size', 1))
            cost_price = float(request.POST.get('cost_price', 0))
            expiry_date = request.POST.get('expiry_date')
            brand = request.POST.get('brand', '')
            strength = request.POST.get('strength', '')
            batch_no = request.POST.get('batch_no', '')
            stock_quantity = int(request.POST.get('stock_quantity', 0))  # packets
            selling_price = float(request.POST.get('selling_price', 0))
            category_id = request.POST.get('category', 1)
            reorder_level = int(request.POST.get('reorder_level', 10))
            invoice_id = request.POST.get('invoice_id')

            # Validation
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

            # Update drug
            drug.generic_name = generic_name
            drug.brand = brand
            drug.dosage = dosage
            drug.strength = strength
            drug.batch_no = batch_no
            drug.pack_size = pack_size
            drug.cost_price = cost_price
            drug.selling_price = selling_price
            drug.stock_quantity = stock_quantity * pack_size  # tablets
            drug.expiry_date = expiry_date
            drug.reorder_level = reorder_level
            drug.category = category
            drug.save()

            # Update or create InvoiceItem
            if current_invoice_item:
                # If invoice changed, we need to update or move the item
                if current_invoice_item.invoice.id != int(invoice_id):
                    # Delete old item, create new one
                    current_invoice_item.delete()
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        drug=drug,
                        quantity=stock_quantity,
                        unit_price=cost_price,
                        total=cost_price * stock_quantity
                    )
                else:
                    # Same invoice – just update fields
                    current_invoice_item.quantity = stock_quantity
                    current_invoice_item.unit_price = cost_price
                    current_invoice_item.total = cost_price * stock_quantity
                    current_invoice_item.save()
            else:
                # No previous invoice item – create new one
                InvoiceItem.objects.create(
                    invoice=invoice,
                    drug=drug,
                    quantity=stock_quantity,
                    unit_price=cost_price,
                    total=cost_price * stock_quantity
                )

            # Recalculate invoice totals for both old and new invoices if they changed
            if current_invoice_item and current_invoice_item.invoice.id != int(invoice_id):
                # Recalc old invoice
                old_inv = current_invoice_item.invoice
                old_inv.total_items = old_inv.items.count()
                old_inv.total_amount = old_inv.items.aggregate(Sum('total'))['total__sum'] or 0
                old_inv.save()
            # Recalc new invoice
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

    # GET request – prefill the invoice dropdown with current invoice
    context = {
        'drug': drug,
        'categories': categories,
        'invoices': invoices,
        'is_edit': True,
        'selected_invoice_id': current_invoice_id,
    }
    return render(request, 'stock/drug_form.html', context)


# ============================================================
# DRUG DELETE - FIXED + RESTRICTED
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_delete(request, drug_id):
    """Delete a drug and all its related records, updating invoice totals."""
    drug = get_object_or_404(Drug, id=drug_id)

    if request.method == 'POST':
        try:
            from django.db.models import Sum

            # ---- 1. Delete all InvoiceItems linked to this drug ----
            invoice_items = InvoiceItem.objects.filter(drug=drug)
            invoices_to_update = set()
            for item in invoice_items:
                invoices_to_update.add(item.invoice)
                item.delete()  # delete the invoice item

            # Update each invoice's total_amount and total_items
            for invoice in invoices_to_update:
                invoice.total_amount = invoice.items.aggregate(Sum('total'))['total__sum'] or 0
                invoice.total_items = invoice.items.count()
                invoice.save()

            # ---- 2. Delete other related records ----
            SaleItem.objects.filter(drug=drug).delete()
            StockMovement.objects.filter(drug=drug).delete()
            PatientMedication.objects.filter(drug=drug).delete()
            ReturnedDrug.objects.filter(drug=drug).delete()

            # ---- 3. Finally delete the drug itself ----
            drug_name = drug.name
            drug.delete()

            messages.success(request, f'Drug "{drug_name}" and all related records deleted successfully!')
            return redirect('stock:drug_list')

        except Exception as e:
            messages.error(request, f'Error deleting drug: {str(e)}')
            import traceback
            traceback.print_exc()
            return redirect('stock:drug_list')

    # GET request – show confirmation page
    return render(request, 'stock/drug_confirm_delete.html', {'drug': drug})


# ============================================================
# ADD STOCK TO DRUG - RESTRICTED
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def add_stock_to_drug(request):
    """
    Add stock to an existing drug, linked to an invoice.
    """
    drugs = Drug.objects.all().order_by('name')
    invoices = Invoice.objects.all().order_by('-invoice_date')
    selected_drug = None

    drug_id = request.GET.get('drug_id')
    if drug_id:
        try:
            selected_drug = Drug.objects.get(id=drug_id)  # ✅ fixed typo
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

        drug = get_object_or_404(Drug, id=drug_id)  # ✅ fixed typo
        invoice = get_object_or_404(Invoice, id=invoice_id)

        # ✅ FIX: add total units (packets × pack size)
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
    """List all suppliers"""
    suppliers = Supplier.objects.all()
    return render(request, 'stock/supplier_list.html', {'suppliers': suppliers})


@login_required
def supplier_create(request):
    """Create a new supplier using SupplierForm"""
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
    """Edit an existing supplier using SupplierForm"""
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
    """Delete a supplier"""
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
    """List all receipts"""
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
    """View receipt details"""
    receipt = get_object_or_404(Receipt, id=receipt_id)
    return render(request, 'stock/receipt_detail.html', {'receipt': receipt})


@login_required
def create_sale_receipt(request):
    """Create a new sale receipt (for retail sale)"""
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

            return JsonResponse({
                'success': True,
                'message': 'Sale completed successfully!',
                'receipt_id': receipt.id,
                'receipt_number': receipt.receipt_number,
                'total_amount': total_amount,
                'change_due': change_due,
                'receipt_url': f'/receipts/{receipt.id}/'
            })

        except Drug.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Drug not found'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)

    drugs = Drug.objects.filter(stock_quantity__gt=0).order_by('name')
    return render(request, 'stock/sale_form.html', {'drugs': drugs})


@login_required
def print_receipt(request, receipt_id):
    """Print receipt (returns a printable version)"""
    receipt = get_object_or_404(Receipt, id=receipt_id)

    if not receipt.is_printed:
        receipt.is_printed = True
        receipt.printed_at = timezone.now()
        receipt.save()

    return render(request, 'stock/receipt_print.html', {'receipt': receipt})


@login_required
def get_daily_sales_api(request):
    """API to get daily sales data for dashboard"""
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
    """List all returned drugs"""
    returns = ReturnedDrug.objects.all().select_related('receipt', 'drug', 'created_by').order_by('-returned_date')
    return render(request, 'stock/return_list.html', {'returns': returns})


@login_required
def return_create(request):
    """Create a new return"""
    if request.method == 'POST':
        try:
            receipt_id = request.POST.get('receipt')
            drug_id = request.POST.get('drug')
            quantity = int(request.POST.get('quantity', 0))
            reason = request.POST.get('reason', '')

            if not receipt_id or not drug_id or quantity <= 0:
                messages.error(request, 'Please fill all required fields correctly.')
                return redirect('stock:return_create')

            receipt = get_object_or_404(Receipt, id=receipt_id)
            drug = get_object_or_404(Drug, id=drug_id)

            receipt_item = None
            for item in receipt.items:
                if item.get('drug_id') == drug.id or item.get('drug_name') == drug.name:
                    receipt_item = item
                    break

            if not receipt_item:
                messages.error(request, 'This drug is not on the selected receipt.')
                return redirect('stock:return_create')

            unit_price = receipt_item.get('unit_price', drug.selling_price)
            from decimal import Decimal
            unit_price = Decimal(str(unit_price))

            return_obj = ReturnedDrug.objects.create(
                receipt=receipt,
                drug=drug,
                quantity=quantity,
                unit_price=unit_price,
                reason=reason,
                created_by=request.user
            )

            drug.stock_quantity += quantity
            drug.save()

            StockMovement.objects.create(
                drug=drug,
                quantity=quantity,
                movement_type='return',
                reference=f"Return from Receipt {receipt.receipt_number}",
                notes=reason,
                created_by=request.user
            )

            messages.success(request, f'Successfully returned {quantity} of "{drug.name}" to stock.')
            return redirect('stock:return_list')

        except Exception as e:
            messages.error(request, f'Error creating return: {str(e)}')
            return redirect('stock:return_create')

    receipts = Receipt.objects.all().order_by('-created_at')
    drugs = Drug.objects.all().order_by('name')
    return render(request, 'stock/return_form.html', {
        'receipts': receipts,
        'drugs': drugs,
    })


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

    # Yesterday
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

        # Generate report data
        report_data = generate_report_data(report_type)

        # Send email (this will skip actual sending in DEBUG mode)
        success = send_report_email(report_data, email, report_type)

        if success:
            # Save report to database
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
        # In DEBUG mode, return detailed error
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
# FIXED: generate_report_data – returns now included correctly
# ============================================================

def generate_report_data(report_type):
    """Generate report data based on type (including returns)"""
    today = timezone.now().date()
    report_data = {
        'report_type': report_type,
        'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sales': {},
        'invoices': {},
        'payment_breakdown': [],
        'top_products': []
    }

    if report_type == 'daily':
        start_date = today
        end_date = today
        report_data['period'] = f"Daily Report - {today.strftime('%B %d, %Y')}"
    elif report_type == 'weekly':
        start_date = today - timedelta(days=7)
        end_date = today
        report_data['period'] = f"Weekly Report - {start_date.strftime('%B %d')} to {end_date.strftime('%B %d, %Y')}"
    elif report_type == 'monthly':
        start_date = today.replace(day=1)
        end_date = today
        report_data['period'] = f"Monthly Report - {today.strftime('%B %Y')}"
    elif report_type == 'annual':
        start_date = today.replace(month=1, day=1)
        end_date = today
        report_data['period'] = f"Annual Report - {today.year}"
    else:
        start_date = today
        end_date = today

    receipts = Receipt.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )

    returns = ReturnedDrug.objects.filter(
        returned_date__date__gte=start_date,
        returned_date__date__lte=end_date
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


def send_report_email(report_data, email, report_type):
    try:
        import base64
        from datetime import datetime, timedelta
        from django.utils import timezone
        from .utils.invoice_pdf import get_invoices_zip, get_invoices_zip_range
        from .utils.report_generator import generate_daily_report_pdf
        from stock.models import Invoice

        print("===== BREVO API EMAIL =====")
        print("Recipient:", email)
        print("Report Type:", report_type)

        # Configure Brevo API
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = os.environ.get("BREVO_API_KEY")

        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )

        # Determine report date based on type
        if report_type == 'daily':
            report_date = timezone.now().date()
            start_date = report_date
            end_date = report_date
        elif report_type == 'weekly':
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=7)
            report_date = end_date
        elif report_type == 'monthly':
            end_date = timezone.now().date()
            start_date = end_date.replace(day=1)
            report_date = end_date
        elif report_type == 'annual':
            end_date = timezone.now().date()
            start_date = end_date.replace(month=1, day=1)
            report_date = end_date
        else:
            report_date = timezone.now().date()
            start_date = report_date
            end_date = report_date

        # Get sales data from report_data
        sales = report_data.get("sales", {})
        invoices_data = report_data.get("invoices", {})
        payment_breakdown = report_data.get("payment_breakdown", [])
        top_products = report_data.get("top_products", [])
        period = report_data.get("period", f"{report_type.capitalize()} Report")
        generated_at = report_data.get("generated_at", timezone.now().strftime('%Y-%m-%d %H:%M:%S'))

        # --- 1. Generate PDF Report ---
        pdf_buffer = generate_comprehensive_report_pdf(report_date)
        pdf_encoded = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')

        # --- 2. Generate ZIP of all invoices ---
        if report_type == 'daily':
            zip_buffer = get_invoices_zip(report_date)
        else:
            invoices_qs = Invoice.objects.filter(
                invoice_date__gte=start_date, 
                invoice_date__lte=end_date
            )
            zip_buffer = get_invoices_zip_range(invoices_qs)

        zip_encoded = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')

        # --- 3. Build payment breakdown rows ---
        payment_rows = ""
        for method in payment_breakdown:
            payment_rows += f"""
            <tr>
                <td>{method.get('method', 'Unknown')}</td>
                <td>UGX {method.get('total', 0):,.0f}</td>
                <td>{method.get('count', 0)}</td>
            </tr>
            """

        # --- 4. Build top products rows ---
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

        # --- 5. Subject ---
        subject = f"{report_type.capitalize()} Sales Report - Miyabala Pharmacy"

        # --- 6. HTML Email Content ---
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
                    <tr>
                        <th>Description</th>
                        <th>Value</th>
                    </tr>
                    <tr>
                        <td>Total Sales</td>
                        <td>UGX {sales.get('total_amount', 0):,.0f}</td>
                    </tr>
                    <tr>
                        <td>Net Sales</td>
                        <td>UGX {sales.get('net_sales', 0):,.0f}</td>
                    </tr>
                    <tr>
                        <td>Total Returns</td>
                        <td>UGX {sales.get('total_returns', 0):,.0f}</td>
                    </tr>
                    <tr>
                        <td>Total Transactions</td>
                        <td>{sales.get('total_transactions', 0)}</td>
                    </tr>
                    <tr>
                        <td>Total Medicines Sold</td>
                        <td>{sales.get('total_items_sold', 0)}</td>
                    </tr>
                    <tr>
                        <td>Total Invoices</td>
                        <td>{invoices_data.get('total_invoices', 0)}</td>
                    </tr>
                    <tr>
                        <td>Average Transaction</td>
                        <td>UGX {sales.get('average_transaction', 0):,.0f}</td>
                    </tr>
                </table>

                <!-- Payment Breakdown -->
                <h3 style="margin-top: 30px;">💳 Payment Breakdown</h3>
                <table>
                    <tr>
                        <th>Method</th>
                        <th>Amount</th>
                        <th>Transactions</th>
                    </tr>
                    {payment_rows}
                    </table>

                <!-- Top Products -->
                <h3 style="margin-top: 30px;">🏆 Top Selling Products</h3>
                <table>
                    <tr>
                        <th>#</th>
                        <th>Product</th>
                        <th>Quantity</th>
                        <th>Total</th>
                    </tr>
                    {product_rows}
                </table>

                <!-- Attachments -->
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

        # --- 7. Send email via Brevo with attachments (TWO RECIPIENTS) ---
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
        print(response)

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
# INVOICE VIEWS
# ============================================================

@login_required
def invoice_list(request):
    """List all invoices"""
    invoices = Invoice.objects.all().select_related('supplier', 'created_by').order_by('-created_at')
    return render(request, 'stock/invoice_list.html', {'invoices': invoices})


@login_required
@user_passes_test(is_admin_or_manager)
def invoice_create(request):
    """Create a new invoice - Admin/Manager only"""
    suppliers = Supplier.objects.all()
    categories = Category.objects.all()
    drugs = Drug.objects.all()

    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.created_by = request.user
            invoice.save()

            # Process invoice items
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
                    # Create InvoiceItem
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        drug_id=drug_id,
                        quantity=quantity,
                        unit_price=unit_price,
                        total=quantity * unit_price
                    )
                    total_amount += quantity * unit_price
                    total_items_count += 1

            # Update invoice totals
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
    """Edit an existing invoice - Admin/Manager only"""
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

            # Delete existing items and recreate from POST
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
    """View invoice details"""
    invoice = get_object_or_404(Invoice, id=invoice_id)
    items = invoice.items.all().select_related('drug')
    return render(request, 'stock/invoice_detail.html', {
        'invoice': invoice,
        'items': items
    })


@login_required
@user_passes_test(is_admin_or_manager)
def invoice_delete(request, invoice_id):
    """Delete an invoice - Admin/Manager only"""
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
    """List all categories"""
    categories = Category.objects.all()
    return render(request, 'stock/category_list.html', {'categories': categories})


# ============================================================
# API VIEWS
# ============================================================

@login_required
def calculate_selling_price(request):
    """API endpoint to calculate selling price"""
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
    """Check if user is admin/superuser"""
    return user.is_superuser


@login_required
@user_passes_test(is_admin_or_manager)
def user_list(request):
    """List all users (admin or manager)"""
    users = User.objects.all()
    return render(request, 'stock/user_list.html', {'users': users})


@login_required
@user_passes_test(is_admin_or_manager)
def user_create(request):
    """Create a new user (admin or manager)"""

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
    """View user details (admin only)"""
    user = get_object_or_404(User, id=user_id)
    return render(request, 'stock/user_detail.html', {'user': user})


@login_required
@user_passes_test(is_admin_or_manager)
def user_edit(request, user_id):
    """Edit a user (admin or manager)"""
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
    """Delete a user (admin or manager)"""
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
    """List all chronic patients"""
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
    """Create a new chronic patient"""
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
    """Edit a chronic patient"""
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
    """View patient details"""
    patient = get_object_or_404(ChronicPatient, id=patient_id)
    return render(request, 'stock/patient_detail.html', {'patient': patient})


@login_required
def patient_delete(request, patient_id):
    """Delete a patient"""
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
    """Add medication to patient"""
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
    """Remove medication from patient"""
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
    """Create test drugs if none exist"""
    from django.contrib.auth.models import User

    if Drug.objects.count() > 0:
        print(f"✅ {Drug.objects.count()} drugs already exist")
        return

    # Full list of categories as requested
    categories_data = [
        'Antibiotic',
        'Anti-hypertensives',
        'Anti-diabetics',
        'Anti-Ulcer',
        'Cough and Flu',
        'Neuro Care',
        'Anti-fungals',
        'Anti-infectives',
        'Painkillers',
        'Beauty and Cosmetics',
        'Vitamins and Minerals',
        'Supplements'
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
