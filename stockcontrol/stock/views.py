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
import json
import traceback
from datetime import datetime, timedelta
from decimal import Decimal

from .models import Drug, Supplier, Invoice, Category, InvoiceItem, Sale, SaleItem, Receipt, Report, ChronicPatient, PatientMedication, PatientVisit


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

@login_required
def get_drugs_api(request):
    """
    API endpoint to get drugs sorted by expiry date (top 10 shortest expiry)
    """
    try:
        # Get drugs sorted by expiry date (soonest first)
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
# DRUG CREATE - FIXED
# ============================================================

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

            # FIX: Convert to proper types
            pack_size = int(request.POST.get('pack_size', 0))
            supplier_id = int(request.POST.get('supplier', 0))
            cost_price = float(request.POST.get('cost_price', 0))
            selling_price = float(request.POST.get('selling_price', 0))
            stock_quantity = int(request.POST.get('stock_quantity', 0))
            category_id = int(request.POST.get('category', 1))
            reorder_level = int(request.POST.get('reorder_level', 10))
            expiry_date = request.POST.get('expiry_date')

            # Debug - print to console
            print(f"Creating Drug: {generic_name}, Dosage: {dosage}, Pack Size: {pack_size}")

            # ========== VALIDATION ==========
            errors = []

            if not generic_name:
                errors.append('Generic Name is required.')

            if not dosage:
                errors.append('Dosage is required.')

            if not supplier_id or supplier_id <= 0:
                errors.append('Supplier is required.')
            else:
                # Verify supplier exists
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

            # Convert date format (dd/mm/yyyy to yyyy-mm-dd)
            if expiry_date and '/' in expiry_date:
                try:
                    parts = expiry_date.split('/')
                    if len(parts) == 3:
                        expiry_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                except:
                    errors.append('Invalid date format. Use dd/mm/yyyy')

            # Verify category exists
            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                errors.append('Selected category does not exist.')

            # If there are errors, show them and return
            if errors:
                for error in errors:
                    messages.error(request, error)
                return render(request, 'stock/drug_form.html', {
                    'categories': categories,
                    'suppliers': suppliers,
                    'is_edit': False
                })

            # ========== CREATE DRUG ==========
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
# DRUG EDIT - FIXED
# ============================================================

@login_required
def drug_edit(request, drug_id):
    """Edit an existing drug/medicine"""
    drug = get_object_or_404(Drug, id=drug_id)
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        try:
            # Get form data
            generic_name = request.POST.get('generic_name')
            brand = request.POST.get('brand')
            dosage = request.POST.get('dosage')
            strength = request.POST.get('strength')
            batch_no = request.POST.get('batch_no')

            # FIX: Convert to proper types
            pack_size = int(request.POST.get('pack_size', 0))
            supplier_id = int(request.POST.get('supplier', 0))
            cost_price = float(request.POST.get('cost_price', 0))
            selling_price = float(request.POST.get('selling_price', 0))
            stock_quantity = int(request.POST.get('stock_quantity', 0))
            category_id = int(request.POST.get('category', 1))
            reorder_level = int(request.POST.get('reorder_level', 10))
            expiry_date = request.POST.get('expiry_date')
            name = request.POST.get('name') or generic_name

            # ========== VALIDATION ==========
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

            # Convert date format (dd/mm/yyyy to yyyy-mm-dd)
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

            # ========== UPDATE DRUG ==========
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
# DRUG DELETE - FIXED
# ============================================================

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
# RECEIPT/SALES VIEWS
# ============================================================

@login_required
def receipt_list(request):
    """List all receipts"""
    receipts = Receipt.objects.all().select_related('created_by').order_by('-created_at')

    # Get today's total sales
    today = timezone.now().date()
    today_receipts = Receipt.objects.filter(created_at__date=today)
    today_total = today_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # Get this month's total
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

            # Process each item
            for item in items:
                drug_id = item.get('drug_id')
                quantity = int(item.get('quantity', 0))
                selling_price = float(item.get('selling_price', 0))

                if quantity <= 0:
                    continue

                drug = Drug.objects.get(id=drug_id)

                # Check stock
                if drug.stock_quantity < quantity:
                    return JsonResponse({
                        'success': False,
                        'message': f'Insufficient stock for {drug.name}. Available: {drug.stock_quantity}'
                    }, status=400)

                # Update stock
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

            # Calculate change
            change_due = amount_paid - total_amount if amount_paid > total_amount else 0

            # Create receipt
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

    # GET request - show sale form
    drugs = Drug.objects.filter(stock_quantity__gt=0).order_by('name')
    return render(request, 'stock/sale_form.html', {'drugs': drugs})


@login_required
def print_receipt(request, receipt_id):
    """Print receipt (returns a printable version)"""
    receipt = get_object_or_404(Receipt, id=receipt_id)

    # Mark as printed
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

        # Get last 10 receipts
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
# REPORT VIEWS
# ============================================================

@login_required
def reports_dashboard(request):
    """Main reports dashboard"""
    # Get today's date
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    
    # Daily Sales
    daily_receipts = Receipt.objects.filter(created_at__date=today)
    daily_total = daily_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    daily_count = daily_receipts.count()
    
    # Weekly Sales
    weekly_receipts = Receipt.objects.filter(created_at__date__gte=week_start, created_at__date__lte=today)
    weekly_total = weekly_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    weekly_count = weekly_receipts.count()
    
    # Monthly Sales
    monthly_receipts = Receipt.objects.filter(created_at__date__gte=month_start, created_at__date__lte=today)
    monthly_total = monthly_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    monthly_count = monthly_receipts.count()
    
    # Annual Sales
    annual_receipts = Receipt.objects.filter(created_at__date__gte=year_start, created_at__date__lte=today)
    annual_total = annual_receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    annual_count = annual_receipts.count()
    
    # Get recent receipts
    recent_receipts = Receipt.objects.all().order_by('-created_at')[:20]
    
    # Get recent invoices
    recent_invoices = Invoice.objects.all().order_by('-created_at')[:10]
    
    # Payment method breakdown for today
    payment_breakdown = daily_receipts.values('payment_method').annotate(
        total=Sum('total_amount'),
        count=Count('id')
    )
    
    # Top selling drugs
    top_drugs = []
    for receipt in Receipt.objects.all()[:100]:
        if receipt.items:
            for item in receipt.items:
                top_drugs.append({
                    'name': item.get('drug_name', 'Unknown'),
                    'quantity': item.get('quantity', 0),
                    'total': item.get('total', 0)
                })
    
    # Aggregate top drugs
    drug_summary = {}
    for drug in top_drugs:
        name = drug['name']
        if name in drug_summary:
            drug_summary[name]['quantity'] += drug['quantity']
            drug_summary[name]['total'] += drug['total']
        else:
            drug_summary[name] = {'quantity': drug['quantity'], 'total': drug['total']}
    
    # Sort and get top 10
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
        
        # Generate report data
        report_data = generate_report_data(report_type)
        
        # Send email
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
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def generate_report_data(report_type):
    """Generate report data based on type"""
    today = timezone.now().date()
    report_data = {
        'report_type': report_type,
        'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sales': {},
        'invoices': {},
        'payment_breakdown': [],
        'top_products': []
    }
    
    # Set date range based on report type
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
    
    # Get receipts within date range
    receipts = Receipt.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    
    # Sales summary
    total_sales = receipts.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_transactions = receipts.count()
    total_items_sold = 0
    
    for receipt in receipts:
        if receipt.items:
            for item in receipt.items:
                total_items_sold += item.get('quantity', 0)
    
    report_data['sales'] = {
        'total_amount': float(total_sales),
        'total_transactions': total_transactions,
        'total_items_sold': total_items_sold,
        'average_transaction': float(total_sales / total_transactions) if total_transactions > 0 else 0,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
    }
    
    # Payment breakdown
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
    
    # Top selling products
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
    
    # Get top 10
    sorted_products = sorted(product_sales.items(), key=lambda x: x[1]['quantity'], reverse=True)[:10]
    for name, data in sorted_products:
        report_data['top_products'].append({
            'name': name,
            'quantity': data['quantity'],
            'total': float(data['total'])
        })
    
    # Invoice summary
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
        # Create email subject
        subject = f"Miyabala Pharmacy - {report_type.capitalize()} Report"
        
        # Create email body
        html_message = render_to_string('stock/report_email.html', {
            'report_data': report_data,
            'report_type': report_type.capitalize(),
            'site_url': 'http://127.0.0.1:8000'
        })
        
        # Send email
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
        # Generate daily report
        report_data = generate_report_data('daily')
        
        # Send to main email
        success = send_report_email(report_data, 'kiyimbahenry314@gmail.com', 'daily')
        
        if success:
            # Save report
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
                invoice_date=invoice_date or timezone.now().date(),
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

# ============================================================
# CHRONIC PATIENT VIEWS
# ============================================================

@login_required
def patient_list(request):
    """List all chronic patients"""
    patients = ChronicPatient.objects.all().select_related('created_by')
    
    # Search functionality
    search_query = request.GET.get('search')
    if search_query:
        patients = patients.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(patient_id__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(location__icontains=search_query)
        )
    
    # Filter by disease type
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
            # Get form data
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
            
            # Validation
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
            
            # Create patient
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
            # Get form data
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
