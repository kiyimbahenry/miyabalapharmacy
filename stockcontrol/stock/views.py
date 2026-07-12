from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
import json
import traceback
from datetime import datetime, timedelta
from decimal import Decimal

# ===== IMPORTS =====
from .models import (
    Drug, Supplier, Invoice, Category, InvoiceItem,
    Sale, SaleItem, Receipt, Report, ChronicPatient,
    PatientMedication, PatientVisit,
    ReturnedDrug, StockMovement
)
# ===== FORM IMPORTS (ADDED SupplierForm) =====
from .forms import SupplierForm, InvoiceForm, DrugForm, StockMovementForm


def is_admin_or_manager(user):
    """Return True if user is superuser or belongs to 'admin' or 'manager' group."""
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=['admin', 'manager']).exists()


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
    """
    API endpoint to get drugs sorted by expiry date (top 10 shortest expiry)
    """
    try:
        drugs = Drug.objects.filter(expiry_date__isnull=False).order_by('expiry_date')[:10]

        data = []
        for drug in drugs:
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
        return JsonResponse(data, safe=False)

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'message': 'Error fetching drugs data'
        }, status=500)


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
    """List all drugs/medicines"""
    drugs = Drug.objects.all().select_related('category', 'supplier')

    category_id = request.GET.get('category')
    if category_id:
        drugs = drugs.filter(category_id=category_id)

    search_query = request.GET.get('search')
    if search_query:
        drugs = drugs.filter(
            Q(name__icontains=search_query) |
            Q(generic_name__icontains=search_query) |
            Q(brand__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    categories = Category.objects.all()

    context = {
        'drugs': drugs,
        'categories': categories,
        'search_query': search_query,
        'selected_category': category_id
    }
    return render(request, 'stock/drug_list.html', context)


# ============================================================
# DRUG CREATE - FIXED + RESTRICTED
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_create(request):
    """Create a new drug/medicine"""
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        try:
            name = request.POST.get('name') or request.POST.get('generic_name')
            generic_name = request.POST.get('generic_name')
            brand = request.POST.get('brand')
            dosage = request.POST.get('dosage')
            strength = request.POST.get('strength')
            batch_no = request.POST.get('batch_no')

            pack_size = int(request.POST.get('pack_size', 0))
            supplier_id = int(request.POST.get('supplier', 0))
            cost_price = float(request.POST.get('cost_price', 0))
            selling_price = float(request.POST.get('selling_price', 0))
            stock_quantity = int(request.POST.get('stock_quantity', 0))
            category_id = int(request.POST.get('category', 1))
            reorder_level = int(request.POST.get('reorder_level', 10))
            expiry_date = request.POST.get('expiry_date')

            print(f"Creating Drug: {generic_name}, Dosage: {dosage}, Pack Size: {pack_size}")

            errors = []

            if not generic_name:
                errors.append('Generic Name is required.')
            if not dosage:
                errors.append('Dosage is required.')
            if not supplier_id or supplier_id <= 0:
                errors.append('Supplier is required.')
            else:
                try:
                    supplier = Supplier.objects.get(id=supplier_id)
                except Supplier.DoesNotExist:
                    errors.append('Selected supplier does not exist.')
            if cost_price <= 0:
                errors.append('Cost Price must be greater than 0.')
            if selling_price <= 0:
                errors.append('Selling Price must be greater than 0.')
            if pack_size <= 0:
                errors.append('Pack Size must be greater than 0.')
            if stock_quantity < 0:
                errors.append('Stock quantity cannot be negative.')
            if not expiry_date:
                errors.append('Expiry Date is required.')
            if expiry_date and '/' in expiry_date:
                try:
                    parts = expiry_date.split('/')
                    if len(parts) == 3:
                        expiry_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                except:
                    errors.append('Invalid date format. Use dd/mm/yyyy')
            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                errors.append('Selected category does not exist.')

            if errors:
                for error in errors:
                    messages.error(request, error)
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            drug = Drug.objects.create(
                name=name or generic_name,
                generic_name=generic_name,
                brand=brand or '',
                dosage=dosage,
                strength=strength or '',
                batch_no=batch_no or '',
                pack_size=pack_size,
                supplier_id=supplier_id,
                category_id=category_id,
                cost_price=cost_price,
                selling_price=selling_price,
                stock_quantity=stock_quantity,
                expiry_date=expiry_date,
                reorder_level=reorder_level,
                created_by=request.user
            )

            messages.success(request, f'Drug "{drug.name}" created successfully!')
            return redirect('stock:drug_list')

        except ValueError as e:
            messages.error(request, f'Please enter valid numbers for numeric fields.')
        except Exception as e:
            messages.error(request, f'Error creating drug: {str(e)}')
            import traceback
            traceback.print_exc()

    context = {
        'categories': categories,
        'suppliers': suppliers,
        'is_edit': False,
    }
    return render(request, 'stock/drug_form.html', context)


# ============================================================
# DRUG CREATE AJAX - FOR INVOICE MODAL
# ============================================================

@login_required
@require_POST
def drug_create_ajax(request):
    """
    AJAX endpoint to create a new drug from the invoice form modal
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
        expiry_date = request.POST.get('expiry_date')
        description = request.POST.get('description', '')

        if not name:
            return JsonResponse({'success': False, 'error': 'Drug name is required.'})
        if not dosage:
            return JsonResponse({'success': False, 'error': 'Dosage is required.'})
        if cost_price <= 0:
            return JsonResponse({'success': False, 'error': 'Cost price must be greater than 0.'})

        drug = Drug.objects.create(
            name=name,
            generic_name=generic_name,
            dosage=dosage,
            strength=strength,
            cost_price=cost_price,
            selling_price=selling_price if selling_price > 0 else cost_price * 1.5,
            pack_size=pack_size,
            supplier_id=supplier_id if supplier_id else None,
            expiry_date=expiry_date if expiry_date else None,
            description=description,
            stock_quantity=0,
            created_by=request.user
        )

        return JsonResponse({
            'success': True,
            'drug_id': drug.id,
            'drug_name': drug.name
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ============================================================
# DRUG EDIT - FIXED + RESTRICTED
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_edit(request, drug_id):
    """Edit an existing drug/medicine"""
    drug = get_object_or_404(Drug, id=drug_id)
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        try:
            generic_name = request.POST.get('generic_name')
            brand = request.POST.get('brand')
            dosage = request.POST.get('dosage')
            strength = request.POST.get('strength')
            batch_no = request.POST.get('batch_no')

            pack_size = int(request.POST.get('pack_size', 0))
            supplier_id = int(request.POST.get('supplier', 0))
            cost_price = float(request.POST.get('cost_price', 0))
            selling_price = float(request.POST.get('selling_price', 0))
            stock_quantity = int(request.POST.get('stock_quantity', 0))
            category_id = int(request.POST.get('category', 1))
            reorder_level = int(request.POST.get('reorder_level', 10))
            expiry_date = request.POST.get('expiry_date')
            name = request.POST.get('name') or generic_name

            errors = []

            if not generic_name:
                errors.append('Generic Name is required.')
            if not dosage:
                errors.append('Dosage is required.')
            if not supplier_id or supplier_id <= 0:
                errors.append('Supplier is required.')
            else:
                try:
                    supplier = Supplier.objects.get(id=supplier_id)
                except Supplier.DoesNotExist:
                    errors.append('Selected supplier does not exist.')
            if cost_price <= 0:
                errors.append('Cost Price must be greater than 0.')
            if selling_price <= 0:
                errors.append('Selling Price must be greater than 0.')
            if pack_size <= 0:
                errors.append('Pack Size must be greater than 0.')
            if stock_quantity < 0:
                errors.append('Stock quantity cannot be negative.')
            if not expiry_date:
                errors.append('Expiry Date is required.')
            if expiry_date and '/' in expiry_date:
                try:
                    parts = expiry_date.split('/')
                    if len(parts) == 3:
                        expiry_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                except:
                    errors.append('Invalid date format. Use dd/mm/yyyy')
            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                errors.append('Selected category does not exist.')

            if errors:
                for error in errors:
                    messages.error(request, error)
                return render(request, 'stock/drug_form.html', {
                    'drug': drug,
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': True
                })

            drug.generic_name = generic_name
            drug.brand = brand or ''
            drug.dosage = dosage
            drug.strength = strength or ''
            drug.batch_no = batch_no or ''
            drug.pack_size = pack_size
            drug.supplier_id = supplier_id
            drug.cost_price = cost_price
            drug.selling_price = selling_price
            drug.stock_quantity = stock_quantity
            drug.expiry_date = expiry_date
            drug.name = name or generic_name
            drug.category_id = category_id
            drug.reorder_level = reorder_level
            drug.save()

            messages.success(request, f'Drug "{drug.name}" updated successfully!')
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
        'suppliers': suppliers,
        'is_edit': True,
    }
    return render(request, 'stock/drug_form.html', context)


# ============================================================
# DRUG DELETE - FIXED + RESTRICTED
# ============================================================

@login_required
@user_passes_test(is_admin_or_manager)
def drug_delete(request, drug_id):
    """Delete a drug/medicine"""
    drug = get_object_or_404(Drug, id=drug_id)

    if request.method == 'POST':
        try:
            drug_name = drug.name
            drug.delete()
            messages.success(request, f'Drug "{drug_name}" deleted successfully!')
            return redirect('stock:drug_list')

        except Exception as e:
            messages.error(request, f'Error deleting drug: {str(e)}')

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

        drug.stock_quantity += quantity
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

        messages.success(request, f'Added {quantity} units of "{drug.name}" to stock via Invoice #{invoice.invoice_number}.')
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
    """Main reports dashboard"""
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    daily_receipts = Receipt.objects.filter(created_at__date=today)
    daily_total = daily_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    daily_count = daily_receipts.count()

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

        report_data = generate_report_data(report_type)

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
    """Send report via email"""
    try:
        subject = f"Miyabala Pharmacy - {report_type.capitalize()} Report"
        html_message = render_to_string('stock/report_email.html', {
            'report_data': report_data,
            'report_type': report_type.capitalize(),
            'site_url': 'http://127.0.0.1:8000'
        })

        send_mail(
            subject,
            f"Please view the HTML version of this email.",
            settings.DEFAULT_FROM_EMAIL or 'noreply@miyabalapharmacy.com',
            [email],
            html_message=html_message,
            fail_silently=False,
        )

        return True

    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def send_auto_reports():
    """Automated function to send daily reports at midnight"""
    try:
        report_data = generate_report_data('daily')
        success = send_report_email(report_data, 'kiyimbahenry314@gmail.com', 'daily')

        if success:
            admin_user = User.objects.filter(is_superuser=True).first()
            Report.objects.create(
                report_type='daily',
                data=report_data,
                generated_by=admin_user,
                sent_to_email=True,
                email_sent_at=timezone.now()
            )
            print(f"✅ Daily report sent successfully at {timezone.now()}")
        else:
            print(f"❌ Failed to send daily report at {timezone.now()}")

    except Exception as e:
        print(f"❌ Error sending auto report: {e}")


# ============================================================
# INVOICE VIEWS
# ============================================================

@login_required
def invoice_list(request):
    """List all invoices"""
    invoices = Invoice.objects.all().select_related('supplier', 'created_by')
    return render(request, 'stock/invoice_list.html', {'invoices': invoices})


@login_required
@user_passes_test(is_admin_or_manager)
def invoice_create(request):
    """Create a new invoice - Admin/Manager only"""
    suppliers = Supplier.objects.all()
    invoices = Invoice.objects.all()
    drugs = Drug.objects.all()  # For the dropdown in the modal

    if request.method == 'POST':
        try:
            invoice_number = request.POST.get('invoice_number')
            supplier_id = request.POST.get('supplier')
            invoice_date = request.POST.get('invoice_date')
            payment_mode = request.POST.get('payment_mode', 'cash')
            total_items = int(request.POST.get('total_items', 0))
            total_cost = float(request.POST.get('total_cost', 0))

            if not invoice_number:
                messages.error(request, 'Invoice Number is required.')
                return render(request, 'stock/invoice_form.html', {
                    'suppliers': suppliers,
                    'invoices': invoices,
                    'drugs': drugs,
                })

            if not supplier_id:
                messages.error(request, 'Please select a supplier.')
                return render(request, 'stock/invoice_form.html', {
                    'suppliers': suppliers,
                    'invoices': invoices,
                    'drugs': drugs,
                })

            invoice = Invoice.objects.create(
                invoice_number=invoice_number,
                supplier_id=supplier_id,
                invoice_date=invoice_date,
                payment_mode=payment_mode,
                total_items=total_items,
                total_cost=total_cost,
                total_amount=0,
                created_by=request.user
            )

            messages.success(request, f'Invoice "{invoice.invoice_number}" created successfully!')
            return redirect('stock:invoice_list')

        except Exception as e:
            messages.error(request, f'Error creating invoice: {str(e)}')
            return render(request, 'stock/invoice_form.html', {
                'suppliers': suppliers,
                'invoices': invoices,
                'drugs': drugs,
            })

    context = {
        'suppliers': suppliers,
        'invoices': invoices,
        'drugs': drugs,
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

    categories_data = [
        'Antibiotic', 'Painkiller', 'Anti-fungals',
        'Beauty and Cosmetics', 'Neuro Care', 'Anti-diabetics',
        'Anti-hypertensives', 'Cough, Cold and Flu', 'Supplements',
        'PUD', 'Vitamins and Minerals', 'Anti-infectives'
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
