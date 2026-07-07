from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import Category, Supplier, Drug, Invoice, InvoiceItem, Sale, SaleItem, StockMovement

# ============================================================
# CUSTOM ADMIN SITE - FIXED
# ============================================================
class CustomAdminSite(admin.AdminSite):  # FIXED: was admin.ModelAdmin, should be admin.AdminSite
    site_header = 'Pharmacy Stock Management'
    site_title = 'Pharmacy Admin'
    index_title = 'Dashboard'

admin_site = CustomAdminSite(name='myadmin')


# ============================================================
# DRUG ADMIN - FIXED
# ============================================================
@admin.register(Drug, site=admin_site)
class DrugAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'generic_name', 'brand', 'dosage', 'strength', 
        'stock_quantity', 'cost_price', 'selling_price', 'expiry_date'
    ]  # FIXED: added 'name' and 'cost_price'
    list_filter = ['dosage', 'category', 'supplier', 'is_active']
    search_fields = ['name', 'generic_name', 'brand', 'batch_no']  # FIXED: added 'name'
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'generic_name', 'brand', 'dosage', 'strength', 'description')  # FIXED: added 'name'
        }),
        ('Pricing & Stock', {
            'fields': ('cost_price', 'selling_price', 'stock_quantity', 'reorder_level', 'max_stock_level', 'pack_size')  # FIXED: min_stock_level → reorder_level
        }),
        ('Additional Information', {
            'fields': ('category', 'supplier', 'expiry_date', 'batch_no', 'barcode', 'is_active', 'markup_percentage')  # FIXED: added barcode, markup_percentage
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============================================================
# CATEGORY ADMIN - FIXED
# ============================================================
@admin.register(Category, site=admin_site)  # FIXED: added @admin.register decorator
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name']


# ============================================================
# SUPPLIER ADMIN - FIXED
# ============================================================
@admin.register(Supplier, site=admin_site)  # FIXED: added @admin.register decorator
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_person', 'phone', 'email', 'created_at']
    search_fields = ['name', 'contact_person', 'email', 'phone']


# ============================================================
# INVOICE ADMIN - FIXED
# ============================================================
class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    readonly_fields = ['total']

@admin.register(Invoice, site=admin_site)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'supplier', 'invoice_date', 'total_amount', 'status', 'created_at']
    # FIXED: removed 'number_of_items' (doesn't exist) and 'supplier_name' (should be 'supplier__name')
    list_filter = ['status', 'invoice_date']
    search_fields = ['invoice_number', 'supplier__name']  # FIXED: supplier_name → supplier__name
    readonly_fields = ['created_at', 'updated_at']
    inlines = [InvoiceItemInline]
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
# SALE ADMIN - FIXED
# ============================================================
class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    readonly_fields = ['total']

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
# STOCK MOVEMENT ADMIN - FIXED
# ============================================================
@admin.register(StockMovement, site=admin_site)  # FIXED: added @admin.register decorator
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['drug', 'quantity', 'movement_type', 'date', 'created_by']
    list_filter = ['movement_type', 'date']
    search_fields = ['drug__name', 'reference']  # FIXED: drug_name → drug__name
    readonly_fields = ['date']


# ============================================================
# REGISTER WITH DEFAULT ADMIN SITE
# ============================================================
admin.site.register(Drug, DrugAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Supplier, SupplierAdmin)
admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Sale, SaleAdmin)
admin.site.register(StockMovement, StockMovementAdmin)
