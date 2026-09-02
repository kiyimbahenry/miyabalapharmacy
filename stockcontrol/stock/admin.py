from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django import forms
from .models import (
    Category, Supplier, Drug, Invoice, InvoiceItem, Sale, SaleItem, StockMovement,
    # NEW MODELS - ADDED WITHOUT CHANGING EXISTING
    Receipt, ReturnedDrug, CreditSale, CreditPayment, DosageForm, 
    ChronicPatient, PatientMedication, PatientVisit, Report
)

# ============================================================
# CUSTOM ADMIN SITE
# ============================================================
class CustomAdminSite(admin.AdminSite):
    site_header = 'Pharmacy Stock Management'
    site_title = 'Pharmacy Admin'
    index_title = 'Dashboard'

admin_site = CustomAdminSite(name='myadmin')


# ============================================================
# DRUG ADMIN FORM – FIXED
# ============================================================
class DrugAdminForm(forms.ModelForm):
    class Meta:
        model = Drug
        fields = '__all__'
        widgets = {
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make category and supplier required
        if 'category' in self.fields:
            self.fields['category'].required = True
            self.fields['category'].empty_label = "-- Select Category --"
        if 'supplier' in self.fields:
            self.fields['supplier'].required = True
            self.fields['supplier'].empty_label = "-- Select Supplier --"
        # Make name optional (we'll set it from generic_name)
        if 'name' in self.fields:
            self.fields['name'].required = False

    def clean(self):
        cleaned_data = super().clean()
        generic_name = cleaned_data.get('generic_name')
        name = cleaned_data.get('name')
        # If name is empty, use generic_name
        if not name and generic_name:
            cleaned_data['name'] = generic_name
        return cleaned_data


# ============================================================
# DRUG ADMIN
# ============================================================
@admin.register(Drug, site=admin_site)
class DrugAdmin(admin.ModelAdmin):
    form = DrugAdminForm
    list_display = [
        'name', 'generic_name', 'brand', 'category', 'supplier', 'dosage', 'strength',
        'stock_quantity', 'cost_price', 'selling_price', 'expiry_date'
    ]
    list_filter = ['dosage', 'category', 'supplier', 'is_active']
    search_fields = ['name', 'generic_name', 'brand', 'batch_no']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['selling_price', 'stock_quantity']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'generic_name', 'brand', 'dosage', 'strength', 'description')
        }),
        ('Category & Supplier', {
            'fields': ('category', 'supplier'),
            'description': 'Select the category and supplier for this drug'
        }),
        ('Pricing & Stock', {
            'fields': ('cost_price', 'selling_price', 'stock_quantity', 'reorder_level', 'max_stock_level', 'pack_size')
        }),
        ('Additional Information', {
            'fields': ('expiry_date', 'batch_no', 'barcode', 'is_active', 'markup_percentage')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============================================================
# CATEGORY ADMIN
# ============================================================
@admin.register(Category, site=admin_site)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name']
    ordering = ['name']


# ============================================================
# SUPPLIER ADMIN
# ============================================================
@admin.register(Supplier, site=admin_site)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_person', 'phone', 'email', 'created_at']
    search_fields = ['name', 'contact_person', 'email', 'phone']
    ordering = ['name']


# ============================================================
# INVOICE ADMIN
# ============================================================
class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    readonly_fields = ['total']
    fields = ['drug', 'quantity', 'unit_price', 'total']
    autocomplete_fields = ['drug']

@admin.register(Invoice, site=admin_site)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'supplier', 'invoice_date', 'total_amount', 'status', 'created_at']
    list_filter = ['status', 'invoice_date']
    search_fields = ['invoice_number', 'supplier__name']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [InvoiceItemInline]
    autocomplete_fields = ['supplier']
    fieldsets = (
        ('Invoice Information', {
            'fields': ('invoice_number', 'supplier', 'invoice_date', 'due_date', 'status')
        }),
        ('Financial', {
            'fields': ('total_amount', 'paid_amount', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============================================================
# SALE ADMIN
# ============================================================
class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    readonly_fields = ['total']
    fields = ['drug', 'quantity', 'unit_price', 'total']
    autocomplete_fields = ['drug']

@admin.register(Sale, site=admin_site)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['sale_number', 'customer_name', 'sale_date', 'total_amount', 'status']
    list_filter = ['status', 'sale_date']
    search_fields = ['sale_number', 'customer_name', 'customer_phone']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [SaleItemInline]
    fieldsets = (
        ('Sale Information', {
            'fields': ('sale_number', 'customer_name', 'customer_phone', 'status')
        }),
        ('Financial', {
            'fields': ('total_amount', 'discount_amount', 'tax_amount', 'net_amount', 'paid_amount', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============================================================
# STOCK MOVEMENT ADMIN
# ============================================================
@admin.register(StockMovement, site=admin_site)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['drug', 'quantity', 'movement_type', 'date', 'created_by']
    list_filter = ['movement_type', 'date']
    search_fields = ['drug__name', 'reference']
    readonly_fields = ['date']
    autocomplete_fields = ['drug']


# ============================================================
# NEW ADMIN CLASSES (ADDED WITHOUT CHANGING EXISTING CODE)
# ============================================================

# 1. RECEIPT ADMIN
@admin.register(Receipt, site=admin_site)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = [
        'receipt_number', 'customer_name', 'total_amount', 'amount_paid', 
        'payment_method', 'is_credit', 'is_cleared', 'created_at'
    ]
    list_filter = ['payment_method', 'is_credit', 'is_cleared', 'created_at']
    search_fields = ['receipt_number', 'customer_name', 'customer_phone']
    readonly_fields = ['receipt_number', 'created_at']
    fieldsets = (
        ('Receipt Information', {
            'fields': ('receipt_number', 'sale', 'customer_name', 'customer_phone')
        }),
        ('Financial', {
            'fields': ('total_amount', 'amount_paid', 'change_due', 'payment_method', 'items')
        }),
        ('Credit Information', {
            'fields': ('is_credit', 'credit_sale', 'is_cleared', 'cleared_date', 'cleared_by'),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'is_printed', 'printed_at'),
            'classes': ('collapse',)
        }),
    )


# 2. RETURNED DRUG ADMIN
@admin.register(ReturnedDrug, site=admin_site)
class ReturnedDrugAdmin(admin.ModelAdmin):
    list_display = ['drug', 'quantity', 'unit_price', 'total_refund', 'receipt', 'returned_date']
    list_filter = ['returned_date']
    search_fields = ['drug__name', 'receipt__receipt_number', 'reason']
    readonly_fields = ['total_refund', 'returned_date']
    fieldsets = (
        ('Return Information', {
            'fields': ('receipt', 'drug', 'quantity', 'unit_price', 'total_refund', 'reason')
        }),
        ('Audit', {
            'fields': ('created_by', 'returned_date'),
            'classes': ('collapse',)
        }),
    )


# 3. CREDIT SALE ADMIN
class CreditPaymentInline(admin.TabularInline):
    model = CreditPayment
    extra = 1
    readonly_fields = ['created_at']
    fields = ['amount', 'payment_method', 'reference', 'notes']
    can_delete = True

@admin.register(CreditSale, site=admin_site)
class CreditSaleAdmin(admin.ModelAdmin):
    list_display = [
        'credit_receipt_number', 'customer_name', 'customer_phone', 
        'total_amount', 'amount_paid', 'remaining_balance', 'status', 
        'due_date', 'created_at'
    ]
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['credit_receipt_number', 'customer_name', 'customer_phone']
    readonly_fields = ['credit_receipt_number', 'remaining_balance', 'created_at', 'updated_at']
    inlines = [CreditPaymentInline]
    fieldsets = (
        ('Credit Information', {
            'fields': ('credit_receipt_number', 'customer_name', 'customer_phone', 'payment_method')
        }),
        ('Financial', {
            'fields': ('total_amount', 'amount_paid', 'remaining_balance', 'items')
        }),
        ('Terms', {
            'fields': ('due_date', 'credit_limit', 'status', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# 4. CREDIT PAYMENT ADMIN
@admin.register(CreditPayment, site=admin_site)
class CreditPaymentAdmin(admin.ModelAdmin):
    list_display = ['credit_sale', 'amount', 'payment_method', 'reference', 'created_at']
    list_filter = ['payment_method', 'created_at']
    search_fields = ['credit_sale__credit_receipt_number', 'credit_sale__customer_name', 'reference']
    readonly_fields = ['created_at']
    fieldsets = (
        ('Payment Information', {
            'fields': ('credit_sale', 'amount', 'payment_method', 'reference', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )


# 5. DOSAGE FORM ADMIN
@admin.register(DosageForm, site=admin_site)
class DosageFormAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'created_by']
    search_fields = ['name']
    ordering = ['name']
    readonly_fields = ['created_at']


# 6. CHRONIC PATIENT ADMIN
class PatientMedicationInline(admin.TabularInline):
    model = PatientMedication
    extra = 1
    fields = ['drug', 'medication_name', 'dosage', 'frequency', 'duration', 'is_active']
    autocomplete_fields = ['drug']

class PatientVisitInline(admin.TabularInline):
    model = PatientVisit
    extra = 1
    readonly_fields = ['visit_date']
    fields = ['visit_type', 'complaints', 'vitals', 'notes', 'next_appointment']

@admin.register(ChronicPatient, site=admin_site)
class ChronicPatientAdmin(admin.ModelAdmin):
    list_display = [
        'patient_id', 'first_name', 'last_name', 'disease_type', 
        'phone', 'next_appointment', 'is_active', 'created_at'
    ]
    list_filter = ['disease_type', 'is_active', 'gender']
    search_fields = ['patient_id', 'first_name', 'last_name', 'phone', 'email']
    readonly_fields = ['patient_id', 'created_at', 'updated_at']
    inlines = [PatientMedicationInline, PatientVisitInline]
    fieldsets = (
        ('Personal Information', {
            'fields': ('patient_id', 'first_name', 'last_name', 'date_of_birth', 'gender', 'phone', 'alternate_phone', 'email')
        }),
        ('Location', {
            'fields': ('location', 'village', 'district')
        }),
        ('Medical Information', {
            'fields': ('disease_type', 'other_disease', 'diagnosis_date', 'medications', 'dosage')
        }),
        ('Appointment', {
            'fields': ('next_appointment', 'is_active')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# 7. REPORT ADMIN
@admin.register(Report, site=admin_site)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['report_type', 'report_date', 'generated_by', 'sent_to_email', 'created_at']
    list_filter = ['report_type', 'sent_to_email', 'created_at']
    search_fields = ['report_type']
    readonly_fields = ['created_at']


# ============================================================
# REGISTER WITH DEFAULT ADMIN SITE
# ============================================================
admin.site.register(Drug, DrugAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Supplier, SupplierAdmin)
admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Sale, SaleAdmin)
admin.site.register(StockMovement, StockMovementAdmin)

# NEW REGISTRATIONS (ADDED WITHOUT CHANGING EXISTING)
admin.site.register(Receipt, ReceiptAdmin)
admin.site.register(ReturnedDrug, ReturnedDrugAdmin)
admin.site.register(CreditSale, CreditSaleAdmin)
admin.site.register(CreditPayment, CreditPaymentAdmin)
admin.site.register(DosageForm, DosageFormAdmin)
admin.site.register(ChronicPatient, ChronicPatientAdmin)
admin.site.register(Report, ReportAdmin)
