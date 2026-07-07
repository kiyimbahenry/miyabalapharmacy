from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test  # FIXED: correct import
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from .models import Drug, Supplier, Invoice, Category, InvoiceItem, Sale, SaleItem
from django.contrib.auth.models import User
import json
from datetime import datetime


# ============================================================
# AUTHENTICATION VIEWS
# ============================================================

def login_view(request):
    """User login view"""
    if request.user.is_authenticated:
        return redirect('stock:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                next_url = request.GET.get('next', '/')
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Please enter both username and password.')

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

@login_required  # FIXED: added @ symbol
def get_drugs_api(request):
    """API endpoint to get drugs sorted by expiry date (top 10 shortest expiry)"""
    try:
        # Get drugs sorted by expiry date (soonest first)
        drugs = Drug.objects.filter(expiry_date__isnull=False).order_by('expiry_date')[:10]

        data = []
        for drug in drugs:
            data.append({
                'id': drug.id,
                'generic': drug.generic_name if drug.generic_name else drug.name,  # FIXED: genetic_name -> generic_name
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
    """API endpoint to complete a drug sale and update stock"""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method',
        }, status=400)

    try:
        data = json.loads(request.body)
        drug_id = data.get('drug_id')
        quantity = int(data.get('quantity', 0))
        payment_method = data.get('payment_method', 'cash')

        # Validate input
        if not drug_id:
            return JsonResponse({
                'success': False,
                'message': 'Drug ID is required',
            }, status=400)

        if quantity <= 0:
            return JsonResponse({
                'success': False,
                'message': 'Quantity must be greater than 0',
            }, status=400)

        # Get the drug
        drug = get_object_or_404(Drug, id=drug_id)

        # Check if enough stock
        if drug.stock_quantity < quantity:
            return JsonResponse({
                'success': False,
                'message': f'Insufficient stock! Available: {drug.stock_quantity}',
            }, status=400)

        # Update stock
        drug.stock_quantity -= quantity
        drug.save()

        return JsonResponse({
            'success': True,
            'message': f'Sold {quantity} of {drug.name}',
            'stock_remaining': drug.stock_quantity,
            'drug_name': drug.name,
            'quantity_sold': quantity,
            'payment_method': payment_method,
            'total_amount': float(drug.selling_price) * quantity
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Drug.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Drug not found'
        }, status=404)
    except Exception as e:
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

    # Filter by category if provided
    category_id = request.GET.get('category')
    if category_id:
        drugs = drugs.filter(category_id=category_id)

    # Search functionality
    search_query = request.GET.get('search')
    if search_query:
        drugs = drugs.filter(
            Q(name__icontains=search_query) |
            Q(generic_name__icontains=search_query) |  # FIXED: genre__name__icontains -> generic_name__icontains
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


@login_required
def drug_create(request):
    """Create a new drug/medicine"""
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        try:
            # Get form data
            name = request.POST.get('name') or request.POST.get('generic_name')
            generic_name = request.POST.get('generic_name')
            brand = request.POST.get('brand')
            dosage = request.POST.get('dosage')
            strength = request.POST.get('strength')
            batch_no = request.POST.get('batch_no')
            pack_size = request.POST.get('pack_size')
            supplier_id = request.POST.get('supplier')
            cost_price = request.POST.get('cost_price')
            selling_price = request.POST.get('selling_price')  # Manually entered from form
            expiry_date = request.POST.get('expiry_date')
            stock_quantity = request.POST.get('stock_quantity')
            category_id = request.POST.get('category', 1)
            reorder_level = request.POST.get('reorder_level', 10)

            # Debug - print to console
            print(f"Creating Drug: {generic_name}, Dosage: {dosage}, Pack Size: {pack_size}")

            # Validate required fields - FIXED: Generic_name -> generic_name
            if not generic_name:
                messages.error(request, 'Generic Name is required.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            if not dosage:
                messages.error(request, 'Dosage is required.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            if not supplier_id:
                messages.error(request, 'Supplier is required.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            if not cost_price or float(cost_price) <= 0:
                messages.error(request, 'Cost Price must be greater than 0.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            if not selling_price or float(selling_price) <= 0:
                messages.error(request, 'Selling Price must be greater than 0.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            if not pack_size or int(pack_size) <= 0:
                messages.error(request, 'Pack Size must be greater than 0.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            if not stock_quantity or int(stock_quantity) < 0:
                messages.error(request, 'Stock quantity must be 0 or more.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            if not expiry_date:
                messages.error(request, 'Expiry Date is required.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            # Create drug - FIXED: added all required fields
            drug = Drug.objects.create(
                name=name,
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

        except Exception as e:
            messages.error(request, f'Error creating drug: {str(e)}')
            import traceback
            traceback.print_exc()  # Print error to console for debugging

    context = {
        'categories': categories,
        'suppliers': suppliers,
        'is_edit': False,
    }
    return render(request, 'stock/drug_form.html', context)


@login_required
def drug_edit(request, drug_id):
    """Edit an existing drug/medicine"""
    drug = get_object_or_404(Drug, id=drug_id)
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        try:
            # Update drug data - FIXED: genric_name -> generic_name
            drug.generic_name = request.POST.get('generic_name')
            drug.brand = request.POST.get('brand')
            drug.dosage = request.POST.get('dosage')
            drug.strength = request.POST.get('strength')
            drug.batch_no = request.POST.get('batch_no')
            drug.pack_size = request.POST.get('pack_size')
            drug.supplier_id = request.POST.get('supplier')
            drug.cost_price = request.POST.get('cost_price')
            drug.selling_price = request.POST.get('selling_price')  # Manually entered
            drug.stock_quantity = request.POST.get('stock_quantity')
            drug.expiry_date = request.POST.get('expiry_date')
            drug.name = request.POST.get('name') or drug.generic_name  # FIXED: genric_name -> generic_name
            drug.category_id = request.POST.get('category', 1)
            drug.reorder_level = request.POST.get('reorder_level', 10)

            drug.save()
            messages.success(request, f'Drug "{drug.name}" updated successfully!')
            return redirect('stock:drug_list')

        except Exception as e:
            messages.error(request, f'Error updating drug: {str(e)}')

    context = {
        'drug': drug,
        'categories': categories,
        'suppliers': suppliers,
        'is_edit': True,
    }
    return render(request, 'stock/drug_form.html', context)


@login_required
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
# SUPPLIER VIEWS
# ============================================================

@login_required
def supplier_list(request):
    """List all suppliers"""
    suppliers = Supplier.objects.all()
    return render(request, 'stock/supplier_list.html', {'suppliers': suppliers})


@login_required
def supplier_create(request):
    """Create a new supplier"""
    if request.method == 'POST':
        try:
            supplier = Supplier.objects.create(
                name=request.POST.get('name'),
                contact_person=request.POST.get('contact_person'),
                email=request.POST.get('email'),
                phone=request.POST.get('phone'),
                address=request.POST.get('address'),
                tax_id=request.POST.get('tax_id'),
                created_by=request.user
            )
            messages.success(request, f'Supplier "{supplier.name}" created successfully!')
            return redirect('stock:supplier_list')
        except Exception as e:
            messages.error(request, f'Error creating supplier: {str(e)}')

    return render(request, 'stock/supplier_form.html')


@login_required
def supplier_edit(request, supplier_id):
    """Edit an existing supplier"""
    supplier = get_object_or_404(Supplier, id=supplier_id)

    if request.method == 'POST':
        try:
            supplier.name = request.POST.get('name')
            supplier.contact_person = request.POST.get('contact_person')
            supplier.email = request.POST.get('email')
            supplier.phone = request.POST.get('phone')
            supplier.address = request.POST.get('address')
            supplier.tax_id = request.POST.get('tax_id')
            supplier.save()

            messages.success(request, f'Supplier "{supplier.name}" updated successfully!')
            return redirect('stock:supplier_list')

        except Exception as e:
            messages.error(request, f'Error updating supplier: {str(e)}')

    return render(request, 'stock/supplier_form.html', {'supplier': supplier})


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
# INVOICE VIEWS
# ============================================================

@login_required
def invoice_list(request):
    """List all invoices"""
    invoices = Invoice.objects.all().select_related('supplier', 'created_by')
    return render(request, 'stock/invoice_list.html', {'invoices': invoices})


@login_required
def invoice_create(request):
    """Create a new invoice"""
    suppliers = Supplier.objects.all()
    drugs = Drug.objects.filter(stock_quantity__gt=0)

    if request.method == 'POST':
        try:
            supplier_id = request.POST.get('supplier')
            invoice_date = request.POST.get('invoice_date')
            invoice_number = request.POST.get('invoice_number')
            notes = request.POST.get('notes')

            # Get drug items from POST - FIXED: use getlist
            drug_ids = request.POST.getlist('drug_ids')
            quantities = request.POST.getlist('quantities')
            unit_prices = request.POST.getlist('unit_prices')

            if not drug_ids or not supplier_id:
                messages.error(request, 'Please select a supplier and at least one drug.')
                return render(request, 'stock/invoice_form.html', {
                    'suppliers': suppliers,
                    'drugs': drugs,
                    'is_edit': False
                })

            # Create invoice
            invoice = Invoice.objects.create(
                supplier_id=supplier_id,
                invoice_number=invoice_number,
                invoice_date=invoice_date or datetime.now().date(),
                notes=notes,
                created_by=request.user
            )

            # Create invoice items
            total_amount = 0
            for i in range(len(drug_ids)):
                if drug_ids[i] and quantities[i] and unit_prices[i]:
                    drug = Drug.objects.get(id=drug_ids[i])
                    quantity = int(quantities[i])
                    unit_price = float(unit_prices[i])
                    total = quantity * unit_price
                    total_amount += total

                    InvoiceItem.objects.create(
                        invoice=invoice,
                        drug=drug,
                        quantity=quantity,
                        unit_price=unit_price,
                        total=total
                    )

                    # Update drug stock
                    drug.stock_quantity += quantity
                    drug.save()

            invoice.total_amount = total_amount
            invoice.save()

            messages.success(request, f'Invoice #{invoice.invoice_number} created successfully!')
            return redirect('stock:invoice_list')

        except Exception as e:
            messages.error(request, f'Error creating invoice: {str(e)}')

    context = {
        'suppliers': suppliers,
        'drugs': drugs,
        'is_edit': False,
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
def invoice_delete(request, invoice_id):
    """Delete an invoice"""
    invoice = get_object_or_404(Invoice, id=invoice_id)

    if request.method == 'POST':
        try:
            # Reverse stock updates
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
@user_passes_test(is_admin)
def user_list(request):
    """List all users (admin only)"""
    users = User.objects.all()
    return render(request, 'stock/user_list.html', {'users': users})


@login_required
@user_passes_test(is_admin)
def user_create(request):
    """Create a new user (admin only)"""
    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            password = request.POST.get('password')
            is_staff = request.POST.get('is_staff') == 'on'
            is_superuser = request.POST.get('is_superuser') == 'on'

            if User.objects.filter(username=username).exists():
                messages.error(request, 'Username already exists.')
                return render(request, 'stock/user_form.html', {'is_edit': False})

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.save()

            messages.success(request, f'User "{username}" created successfully!')
            return redirect('stock:user_list')

        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')

    return render(request, 'stock/user_form.html', {'is_edit': False})


@login_required
@user_passes_test(is_admin)
def user_edit(request, user_id):
    """Edit a user (admin only)"""
    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        try:
            user.username = request.POST.get('username')
            user.email = request.POST.get('email')
            user.is_staff = request.POST.get('is_staff') == 'on'
            user.is_superuser = request.POST.get('is_superuser') == 'on'

            password = request.POST.get('password')
            if password:
                user.set_password(password)

            user.save()
            messages.success(request, f'User "{user.username}" updated successfully!')
            return redirect('stock:user_list')

        except Exception as e:
            messages.error(request, f'Error updating user: {str(e)}')

    return render(request, 'stock/user_form.html', {
        'user': user,
        'is_edit': True
    })


@login_required
@user_passes_test(is_admin)
def user_delete(request, user_id):
    """Delete a user (admin only)"""
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
