from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    Category, Supplier, Drug, Invoice, InvoiceItem, 
    Sale, SaleItem, StockMovement
)

# ============ CATEGORY ADMIN ============

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['name']
    list_per_page = 20

# ============ SUPPLIER ADMIN ============

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_person', 'phone', 'email', 'created_at']
    search_fields = ['name', 'contact_person', 'email', 'phone', 'tax_id']
    list_filter = ['created_at']
    ordering = ['name']
    list_per_page = 20

# ============ DRUG (MEDICINE) ADMIN ============

@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'brand', 'category', 'supplier', 
        'stock_quantity', 'selling_price', 'is_low_stock_display', 
        'is_expired_display', 'expiry_date'
    ]
    search_fields = ['name', 'brand', 'generic_name', 'barcode']
    list_filter = ['category', 'supplier', 'is_active', 'expiry_date']
    ordering = ['name']
    list_per_page = 20
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'brand', 'generic_name', 'description', 'category', 'supplier')
        }),
        ('Pricing and Stock', {
            'fields': ('purchase_price', 'selling_price', 'stock_quantity', 'reorder_level', 'max_stock_level')
        }),
        ('Additional Information', {
            'fields': ('expiry_date', 'barcode', 'is_active')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']
    
    def is_low_stock_display(self, obj):
        """Display low stock status with color coding"""
        if obj.stock_quantity <= obj.reorder_level:
            return format_html('<span style="color: red; font-weight: bold;">🔴 Low Stock</span>')
        elif obj.stock_quantity <= obj.reorder_level * 2:
            return format_html('<span style="color: orange;">🟡 Medium</span>')
        return format_html('<span style="color: green;">🟢 In Stock</span>')
    is_low_stock_display.short_description = 'Stock Status'
    
    def is_expired_display(self, obj):
        """Display expired status with color coding"""
        if obj.expiry_date:
            if obj.expiry_date < timezone.now().date():
                return format_html('<span style="color: red; font-weight: bold;">🚫 Expired</span>')
            elif (obj.expiry_date - timezone.now().date()).days <= 30:
                return format_html('<span style="color: orange;">⚠️ Expiring Soon</span>')
        return format_html('<span style="color: green;">✅ Valid</span>')
    is_expired_display.short_description = 'Expiry Status'
    
    actions = ['mark_as_active', 'mark_as_inactive', 'adjust_stock']
    
    def mark_as_active(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} drug(s) marked as active.")
    mark_as_active.short_description = "Mark selected drugs as Active"
    
    def mark_as_inactive(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} drug(s) marked as inactive.")
    mark_as_inactive.short_description = "Mark selected drugs as Inactive"
    
    def adjust_stock(self, request, queryset):
        # This would open a form for stock adjustment
        self.message_user(request, "Stock adjustment feature coming soon.")
    adjust_stock.short_description = "Adjust stock for selected drugs"

# ============ INVOICE ADMIN ============

class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    fields = ['drug', 'quantity', 'unit_price', 'total']
    readonly_fields = ['total']
    can_delete = True

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'invoice_number', 'supplier', 'invoice_date', 
        'total_amount', 'status', 'balance_due_display', 'created_at'
    ]
    search_fields = ['invoice_number', 'supplier__name']
    list_filter = ['status', 'invoice_date', 'created_at']
    ordering = ['-invoice_date']
    list_per_page = 20
    inlines = [InvoiceItemInline]
    
    fieldsets = (
        ('Invoice Information', {
            'fields': ('invoice_number', 'supplier', 'invoice_date', 'due_date', 'status')
        }),
        ('Financial Details', {
            'fields': ('total_amount', 'paid_amount', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']
    
    def balance_due_display(self, obj):
        """Display balance due with color coding"""
        balance = obj.balance_due
        if balance <= 0:
            return format_html('<span style="color: green;">✅ Paid</span>')
        return format_html('<span style="color: red;">💰 ${:.2f}</span>', balance)
    balance_due_display.short_description = 'Balance Due'

# ============ SALE ADMIN ============

class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    fields = ['drug', 'quantity', 'unit_price', 'total']
    readonly_fields = ['total']
    can_delete = True

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        'sale_number', 'customer_name', 'sale_date', 
        'net_amount', 'status', 'created_at'
    ]
    search_fields = ['sale_number', 'customer_name', 'customer_phone']
    list_filter = ['status', 'sale_date', 'created_at']
    ordering = ['-sale_date']
    list_per_page = 20
    inlines = [SaleItemInline]
    
    fieldsets = (
        ('Sale Information', {
            'fields': ('sale_number', 'customer_name', 'customer_phone', 'status')
        }),
        ('Financial Details', {
            'fields': ('total_amount', 'discount_amount', 'tax_amount', 'net_amount', 'paid_amount')
        }),
        ('Additional Information', {
            'fields': ('notes',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']

# ============ STOCK MOVEMENT ADMIN ============

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['drug', 'quantity_display', 'movement_type', 'date', 'reference', 'created_by']
    search_fields = ['drug__name', 'reference', 'notes']
    list_filter = ['movement_type', 'date', 'created_by']
    ordering = ['-date']
    list_per_page = 30
    readonly_fields = ['date']
    
    def quantity_display(self, obj):
        """Display quantity with color coding"""
        if obj.quantity > 0:
            return format_html('<span style="color: green;">+{}</span>', obj.quantity)
        else:
            return format_html('<span style="color: red;">{}</span>', obj.quantity)
    quantity_display.short_description = 'Quantity'
    
    fieldsets = (
        ('Movement Information', {
            'fields': ('drug', 'quantity', 'movement_type', 'reference')
        }),
        ('Additional Information', {
            'fields': ('notes', 'date', 'created_by')
        }),
    )
    readonly_fields = ['date']

# ============ REGISTER ALL MODELS ============

# Register any models that weren't registered with decorators
# (All models are already registered with the @admin.register decorator above)

# Customize admin site header
admin.site.site_header = "Pharmacy Stock Management System"
admin.site.site_title = "Pharmacy Admin"
admin.site.index_title = "Dashboard"
