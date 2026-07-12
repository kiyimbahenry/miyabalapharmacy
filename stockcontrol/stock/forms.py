from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Supplier, Invoice, Drug, Category, StockMovement

# ============ SUPPLIER FORM ============
class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_person', 'phone', 'email', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Supplier name'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contact person name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Physical address', 'rows': 3}),
        }

# ============ INVOICE FORM ============
class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['invoice_number', 'supplier', 'invoice_date', 'payment_mode', 'total_cost']
        widgets = {
            'invoice_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'INV-001'}),
            'supplier': forms.Select(attrs={'class': 'form-control'}),
            'invoice_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_mode': forms.Select(attrs={'class': 'form-control'}),
            'total_cost': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Enter total cost', 'step': '0.01'}),
        }

# ============ DRUG FORM ============
class DrugForm(forms.ModelForm):
    class Meta:
        model = Drug
        fields = [
            'name', 'generic_name', 'brand', 'dosage', 'strength',
            'category', 'supplier', 'cost_price', 'selling_price',
            'stock_quantity', 'reorder_level', 'expiry_date', 'batch_no',
            'pack_size', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Drug name'}),
            'generic_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Generic name'}),
            'brand': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brand name'}),
            'dosage': forms.Select(attrs={'class': 'form-control'}),
            'strength': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 500mg'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'supplier': forms.Select(attrs={'class': 'form-control'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
            'reorder_level': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '10'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'batch_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Batch number'}),
            'pack_size': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        cost_price = cleaned_data.get('cost_price')
        selling_price = cleaned_data.get('selling_price')
        stock_quantity = cleaned_data.get('stock_quantity')

        # Auto-calculate selling price if not set
        if cost_price and (not selling_price or selling_price == 0):
            cleaned_data['selling_price'] = cost_price * 1.5

        # Validate stock quantity
        if stock_quantity is not None and stock_quantity < 0:
            raise forms.ValidationError("Stock quantity cannot be negative")

        # Validate cost price
        if cost_price is not None and cost_price < 0:
            raise forms.ValidationError("Cost price cannot be negative")

        # Validate selling price
        if selling_price is not None and selling_price < 0:
            raise forms.ValidationError("Selling price cannot be negative")

        return cleaned_data

# ============ STOCK MOVEMENT FORM ============
class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ['drug', 'movement_type', 'quantity', 'notes']
        widgets = {
            'drug': forms.Select(attrs={'class': 'form-control'}),
            'movement_type': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Notes', 'rows': 3}),
        }
