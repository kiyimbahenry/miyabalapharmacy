from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from .models import Drug, Supplier, Invoice, Category, InvoiceItem
from django.contrib.auth.models import User
import json
from datetime import datetime

# ============ AUTHENTICATION VIEWS ============

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

# ============ DASHBOARD VIEW ============

@login_required
def dashboard(request):
    """Dashboard view showing statistics and recent data"""
    # Get statistics
    total_medicines = Drug.objects.count()
    total_suppliers = Supplier.objects.count()
    total_invoices = Invoice.objects.count()
    low_stock_count = Drug.objects.filter(stock_quantity__lte=10).count()
    
    # Get recent medicines (last 5)
    recent_medicines = Drug.objects.all().order_by('-id')[:5]
    
    # Calculate total stock value - Simple way that works
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

# ============ DRUG (MEDICINE) VIEWS ============

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
            Q(brand__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    categories = Category.objects.all()
    
    context = {
        'drugs': drugs,
        'categories': categories,
        'search_query': search_query,
        'selected_category': category_id,
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
            name = request.POST.get('name')
            brand = request.POST.get('brand')
            category_id = request.POST.get('category')
            supplier_id = request.POST.get('supplier')
            description = request.POST.get('description')
            purchase_price = request.POST.get('purchase_price')
            selling_price = request.POST.get('selling_price')
            stock_quantity = request.POST.get('stock_quantity')
            reorder_level = request.POST.get('reorder_level')
            expiry_date = request.POST.get('expiry_date')
            barcode = request.POST.get('barcode')
            
            # Validate required fields
            if not all([name, category_id, supplier_id, purchase_price, selling_price, stock_quantity]):
                messages.error(request, 'Please fill in all required fields.')
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })
            
            # Create drug
            drug = Drug.objects.create(
                name=name,
                brand=brand,
                category_id=category_id,
                supplier_id=supplier_id,
                description=description,
                purchase_price=purchase_price,
                selling_price=selling_price,
                stock_quantity=stock_quantity,
                reorder_level=reorder_level or 10,
                expiry_date=expiry_date if expiry_date else None,
                barcode=barcode,
                created_by=request.user
            )
            
            messages.success(request, f'Drug "{drug.name}" created successfully!')
            return redirect('stock:drug_list')
            
        except Exception as e:
            messages.error(request, f'Error creating drug: {str(e)}')
    
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
            # Update drug data
            drug.name = request.POST.get('name')
            drug.brand = request.POST.get('brand')
            drug.category_id = request.POST.get('category')
            drug.supplier_id = request.POST.get('supplier')
            drug.description = request.POST.get('description')
            drug.purchase_price = request.POST.get('purchase_price')
            drug.selling_price = request.POST.get('selling_price')
            drug.stock_quantity = request.POST.get('stock_quantity')
            drug.reorder_level = request.POST.get('reorder_level')
            drug.expiry_date = request.POST.get('expiry_date')
            drug.barcode = request.POST.get('barcode')
            
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

# ============ SUPPLIER VIEWS ============

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
    
    return render(request, 'stock/supplier_form.html', {'is_edit': False})

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
    
    return render(request, 'stock/supplier_form.html', {
        'supplier': supplier,
        'is_edit': True
    })

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

# ============ INVOICE VIEWS ============

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
            
            # Get drug items from POST
            drug_ids = request.POST.getlist('drug_ids[]')
            quantities = request.POST.getlist('quantities[]')
            unit_prices = request.POST.getlist('unit_prices[]')
            
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

# ============ CATEGORY VIEWS ============

@login_required
def category_list(request):
    """List all categories"""
    categories = Category.objects.all()
    return render(request, 'stock/category_list.html', {'categories': categories})

# ============ API VIEWS ============

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

# ============ USER MANAGEMENT VIEWS (Admin only) ============

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
    
    return render(request, 'stock/user_confirm_delete.html', {'user': user})
