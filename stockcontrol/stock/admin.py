from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django import forms
from .models import Category, Supplier, Drug, Invoice, InvoiceItem, Sale, SaleItem, StockMovement

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
# REGISTER WITH DEFAULT ADMIN SITE
# ============================================================
admin.site.register(Drug, DrugAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Supplier, SupplierAdmin)
admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Sale, SaleAdmin)
admin.site.register(StockMovement, StockMovementAdmin)
