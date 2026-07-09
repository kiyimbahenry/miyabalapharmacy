from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

# CATEGORY MODEL
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

# SUPPLIER MODEL
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

# DRUG (MEDICINE) MODEL
class Drug(models.Model):
    """Medicine/Drug model"""

    # Dosage Form Choices
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

    # Basic Information
    name = models.CharField(max_length=200)
    generic_name = models.CharField(max_length=200, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    # Dosage Field
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

    # Pricing and Stock
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    stock_quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=10)
    max_stock_level = models.PositiveIntegerField(default=100, blank=True, null=True)

    # Additional Information
    expiry_date = models.DateField(blank=True, null=True)
    batch_no = models.CharField(max_length=50, blank=True, null=True, help_text="Batch/Lot number")
    barcode = models.CharField(max_length=100, blank=True, null=True, unique=True)
    is_active = models.BooleanField(default=True)

    # Pack Size
    pack_size = models.PositiveIntegerField(
        default=0,
        help_text="Number of units per packet"
    )

    # Markup Percentage
    markup_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,
        help_text="Default 50% (1.5x cost price)"
    )

    # Audit Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="drugs_created")

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["batch_no"]),
            models.Index(fields=["expiry_date"]),
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

    def save(self, *args, **kwargs):
        """Save the drug"""
        # Commented out to fix the multiplication error
        # if self.cost_price:
        #     self.selling_price = self.cost_price * (1 + self.markup_percentage / 100)
        #     self.selling_price = round(self.selling_price, 2)
        super().save(*args, **kwargs)


# INVOICE MODEL
class Invoice(models.Model):
    """Invoice model for purchases from suppliers"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('canceled', 'Canceled'),
    ]

    PAYMENT_MODE_CHOICES = [
        ('cash', 'Cash'),
        ('credit', 'Credit'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='invoices')
    invoice_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_items = models.PositiveIntegerField(default=0, help_text="Total number of items on this invoice")
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODE_CHOICES, default='cash')
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='invoices_created')

    class Meta:
        ordering = ['-invoice_date', 'created_at']

    def __str__(self):
        return f"Invoice #{self.invoice_number} - {self.supplier.name}"

    @property
    def balance_due(self):
        return self.total_amount - self.paid_amount

    @property
    def is_paid(self):
        return self.balance_due <= 0


# INVOICE ITEM MODEL
class InvoiceItem(models.Model):
    """Invoice line items"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name='invoice_items')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.drug.name} x {self.quantity} - {self.invoice.invoice_number}"

    def save(self, *args, **kwargs):
        # FIX: Convert both to Decimal to avoid float multiplication error
        self.total = Decimal(self.quantity) * Decimal(self.unit_price)
        super().save(*args, **kwargs)


# SALE MODEL
class Sale(models.Model):
    """Sales model for customer purchases"""
    SALE_STATUS = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('canceled', 'Canceled'),
    ]

    sale_number = models.CharField(max_length=50, unique=True)
    sale_date = models.DateTimeField(auto_now_add=True)
    customer_name = models.CharField(max_length=200, blank=True, null=True)
    customer_phone = models.CharField(max_length=20, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=SALE_STATUS, default='pending')
    notes = models.TextField(blank=True, null=True)

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


# SALE ITEM MODEL
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
        # FIX: Convert both to Decimal to avoid float multiplication error
        self.total = Decimal(self.quantity) * Decimal(self.unit_price)
        super().save(*args, **kwargs)


# STOCK MOVEMENT MODEL
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
    quantity = models.IntegerField()
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    reference = models.CharField(max_length=200, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='stock_movements')

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.drug.name} x {self.quantity} - {self.movement_type}"

# RECEIPT MODEL

class Receipt(models.Model):
    """Receipt model for tracking sales"""
    receipt_number = models.CharField(max_length=50, unique=True)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='receipts', null=True, blank=True)
    customer_name = models.CharField(max_length=200, blank=True, null=True)
    customer_phone = models.CharField(max_length=20, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    change_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=50, default='cash')
    items = models.JSONField(default=list)  # Store items as JSON
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='receipts_created')
    is_printed = models.BooleanField(default=False)
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['receipt_number']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Receipt #{self.receipt_number} - {self.total_amount} UGX"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            # Generate receipt number: REC-YYYYMMDD-XXXX
            today = timezone.now().strftime('%Y%m%d')
            count = Receipt.objects.filter(created_at__date=timezone.now().date()).count() + 1
            self.receipt_number = f"REC-{today}-{str(count).zfill(4)}"
        super().save(*args, **kwargs)

# REPORT MODEL

class Report(models.Model):
    """Report model for tracking system activities"""
    REPORT_TYPES = [
        ('daily', 'Daily Report'),
        ('weekly', 'Weekly Report'),
        ('monthly', 'Monthly Report'),
        ('annual', 'Annual Report'),
    ]

    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    report_date = models.DateField(auto_now_add=True)
    data = models.JSONField(default=dict)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_to_email = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_report_type_display()} - {self.report_date}"

# ============================================================
# CHRONIC PATIENT MODELS
# ============================================================

class ChronicPatient(models.Model):
    """Model for chronic disease patients"""

    DISEASE_CHOICES = [
        ('HIV', 'HIV/AIDS'),
        ('HYPERTENSION', 'Hypertension'),
        ('DM', 'Diabetes Mellitus'),
        ('NEURO', 'Neuro Care'),
        ('ULCERS', 'Ulcers'),
        ('ASTHMA', 'Asthma'),
        ('CANCER', 'Cancer'),
        ('KIDNEY', 'Kidney Disease'),
        ('HEART', 'Heart Disease'),
        ('OTHER', 'Other'),
    ]

    patient_id = models.CharField(max_length=50, unique=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')], blank=True)
    phone = models.CharField(max_length=20, blank=True)
    alternate_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True, null=True)
    location = models.TextField(blank=True)
    village = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)

    # Disease Information
    disease_type = models.CharField(max_length=20, choices=DISEASE_CHOICES)
    other_disease = models.CharField(max_length=100, blank=True, help_text="Specify if disease is 'Other'")
    diagnosis_date = models.DateField(null=True, blank=True)

    # Treatment Information
    medications = models.TextField(blank=True, help_text="List of medications the patient is taking")
    dosage = models.TextField(blank=True, help_text="Dosage information for each medication")
    next_appointment = models.DateField(null=True, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='patients_created')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient_id']),
            models.Index(fields=['first_name', 'last_name']),
            models.Index(fields=['disease_type']),
        ]

    def __str__(self):
        return f"{self.patient_id} - {self.first_name} {self.last_name} ({self.get_disease_type_display()})"

    def save(self, *args, **kwargs):
        if not self.patient_id:
            # Generate patient ID: CHR-YYYY-XXXX
            year = timezone.now().year
            count = ChronicPatient.objects.filter(created_at__year=year).count() + 1
            self.patient_id = f"CHR-{year}-{str(count).zfill(4)}"
        super().save(*args, **kwargs)


class PatientMedication(models.Model):
    """Model for patient medications"""
    patient = models.ForeignKey(ChronicPatient, on_delete=models.CASCADE, related_name='medication_list')
    drug = models.ForeignKey(Drug, on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_medications')
    medication_name = models.CharField(max_length=200)
    dosage = models.CharField(max_length=100, help_text="e.g., 500mg twice daily")
    frequency = models.CharField(max_length=100, help_text="e.g., Morning, Evening, Daily")
    duration = models.CharField(max_length=100, blank=True, help_text="e.g., 3 months, Ongoing")
    start_date = models.DateField(auto_now_add=True)
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.patient.first_name} {self.patient.last_name} - {self.medication_name}"


class PatientVisit(models.Model):
    """Model for patient visit history"""
    patient = models.ForeignKey(ChronicPatient, on_delete=models.CASCADE, related_name='visits')
    visit_date = models.DateTimeField(auto_now_add=True)
    visit_type = models.CharField(max_length=50, choices=[
        ('regular', 'Regular Checkup'),
        ('emergency', 'Emergency'),
        ('followup', 'Follow-up'),
        ('medication', 'Medication Pickup'),
    ], default='regular')
    complaints = models.TextField(blank=True)
    vitals = models.JSONField(default=dict, blank=True, help_text="Blood Pressure, Heart Rate, Temperature, etc.")
    notes = models.TextField(blank=True)
    next_appointment = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='patient_visits')

    class Meta:
        ordering = ['-visit_date']

    def __str__(self):
        return f"{self.patient.first_name} {self.patient.last_name} - {self.visit_date.strftime('%Y-%m-%d')}"
