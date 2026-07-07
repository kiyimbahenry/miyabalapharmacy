from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

# ============================================================
# CATEGORY MODEL
# ============================================================
class Category(models.Model):
    """Medicine category model"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ============================================================
# SUPPLIER MODEL
# ============================================================
class Supplier(models.Model):
    """Supplier model"""
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='suppliers_created')

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ============================================================
# DRUG (MEDICINE) MODEL - FIXED
# ============================================================
class Drug(models.Model):
    """Medicine/Drug model"""
    markup_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,
        help_text="Default 50% (1.5x cost price)"
)
    
    # Dosage Form Choices - FIXED (removed duplicates)
    DOSAGE_CHOICES = [
        ('tablet', 'Tablet'),
        ('capsules', 'Capsules'),
        ('injection', 'Injection'),
        ('syrup', 'Syrup'),
        ('suspension', 'Suspension'),
        ('drops', 'Drops'),
        ('ointment', 'Ointment'),
        ('cream', 'Cream'),
        ('jerry', 'Jerry'),
        ('oil', 'Oil'),
        ('spray', 'Spray'),
        ('gel', 'Gel'),
        ('powder', 'Powder'),
        ('liquid', 'Liquid'),
        ('balm', 'Balm'),
    ]
    
    # Basic Information - FIXED (added name field)
    name = models.CharField(max_length=200)
    generic_name = models.CharField(max_length=200, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    
    # Dosage Field - FIXED (removed duplicate)
    dosage = models.CharField(
        max_length=50, 
        choices=DOSAGE_CHOICES, 
        default='tablet', 
        blank=True, 
        null=True,
        help_text="Select the dosage form"
    )
    
    strength = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text="e.g., 500mg, 10mg/5ml"
    )

    # Relationships
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='drugs')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, related_name='drugs')

    # Pricing and Stock - FIXED (changed CharField to DecimalField)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=10)  # FIXED: renamed from min_stock_level
    max_stock_level = models.PositiveIntegerField(default=100, blank=True, null=True)

    # Additional Information
    expiry_date = models.DateField(blank=True, null=True)
    batch_no = models.CharField(max_length=50, blank=True, null=True, help_text="Batch/Lot number")  # FIXED
    barcode = models.CharField(max_length=100, blank=True, null=True, unique=True)  # FIXED: removed unique from batch_no
    is_active = models.BooleanField(default=True)
    
    # NEW: Pack Size field
    pack_size = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="e.g., 10 tablets, 100ml"
    )
    
    # NEW: Markup Percentage for auto-calculating selling price
    markup_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,
        help_text="Default 50% (1.5x cost price)"
    )

    # Audit Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='drugs_created')

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['batch_no']),  # FIXED: removed dot
            models.Index(fields=['expiry_date']),
        ]

    def __str__(self):
        return f"{self.name} ({self.stock_quantity} units)"

    @property
    def is_low_stock(self):
        """Check if stock is low"""
        return self.stock_quantity <= self.reorder_level

    @property
    def is_expired(self):
        """Check if drug is expired"""
        if self.expiry_date:
            return self.expiry_date < timezone.now().date()
        return False

    @property
    def profit_margin(self):
        """Calculate profit margin"""
        if self.cost_price > 0:
            return ((self.selling_price - self.cost_price) / self.cost_price) * 100
        return 0
    
    @property
    def calculated_selling_price(self):
        """Auto-calculate selling price based on markup"""
        if self.cost_price > 0:
            return self.cost_price * (1 + self.markup_percentage / 100)
        return 0
    
    def save(self, *args, **kwargs):
        """Auto-calculate selling price before saving"""
        if self.cost_price:
            self.selling_price = self.cost_price * (1 + self.markup_percentage / 100)
            self.selling_price = round(self.selling_price, 2)
        super().save(*args, **kwargs)


# ============================================================
# INVOICE MODEL
# ============================================================
class Invoice(models.Model):
    """Invoice model for purchases from suppliers"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('canceled', 'Canceled'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='invoices')
    invoice_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # FIXED: removed quotes
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, null=True)

    # Audit Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='invoices_created')

    class Meta:
        ordering = ['-invoice_date', 'created_at']

    def __str__(self):
        return f"Invoice #{self.invoice_number} - {self.supplier.name}"

    @property
    def balance_due(self):
        """Calculate remaining balance"""
        return self.total_amount - self.paid_amount

    @property
    def is_paid(self):
        """Check if invoice is fully paid"""
        return self.balance_due <= 0


# ============================================================
# INVOICE ITEM MODEL
# ============================================================
class InvoiceItem(models.Model):
    """Invoice line items"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name='invoice_items')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.drug.name} x {self.quantity} - {self.invoice.invoice_number}"

    def save(self, *args, **kwargs):
        """Calculate total before saving"""
        self.total = Decimal(self.quantity) * self.unit_price
        super().save(*args, **kwargs)


# ============================================================
# SALE MODEL
# ============================================================
class Sale(models.Model):
    """Sales model for customer purchases"""
    SALE_STATUS = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('canceled', 'Canceled'),
    ]

    sale_number = models.CharField(max_length=50, unique=True)
    sale_date = models.DateTimeField(auto_now_add=True)  # FIXED: changed to DateTimeField
    customer_name = models.CharField(max_length=200, blank=True, null=True)
    customer_phone = models.CharField(max_length=20, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # FIXED: removed quotes
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # FIXED: removed quotes
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=SALE_STATUS, default='pending')
    notes = models.TextField(blank=True, null=True)

    # Audit Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sales_created')

    class Meta:
        ordering = ['-sale_date']

    def __str__(self):
        return f"Sale #{self.sale_number} - {self.customer_name or 'Walk-in Customer'}"

    @property
    def balance_due(self):
        return self.net_amount - self.paid_amount


# ============================================================
# SALE ITEM MODEL
# ============================================================
class SaleItem(models.Model):
    """Sale line items"""
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name='sale_items')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.drug.name} x {self.quantity} - {self.sale.sale_number}"

    def save(self, *args, **kwargs):
        """Calculate total before saving"""
        self.total = Decimal(self.quantity) * self.unit_price
        super().save(*args, **kwargs)  # FIXED: removed underscore


# ============================================================
# STOCK MOVEMENT MODEL
# ============================================================
class StockMovement(models.Model):
    """Track stock movements (in/out)"""
    MOVEMENT_TYPES = [
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
        ('return', 'Return'),
        ('adjustment', 'Adjustment'),
        ('expiry', 'Expiry'),
        ('transfer', 'Transfer'),
    ]

    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name='stock_movements')
    quantity = models.IntegerField()  # Positive for inbound, negative for outbound
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    reference = models.CharField(max_length=200, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)  # FIXED: changed to DateTimeField
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='stock_movements')

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.drug.name} x {self.quantity} - {self.movement_type}"
