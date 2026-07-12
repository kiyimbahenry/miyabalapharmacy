from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Supplier, Invoice, Drug, Category, UserProfile, StockMovement

# ============ SUPPLIER FORM ============
class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_person', 'phone', 'email', 'location']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Supplier name'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contact person name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'location': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Physical location', 'rows': 3}),
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
            'name', 'category', 'drug_type', 'generic_name', 
            'manufacturer', 'batch_number', 'expiry_date',
            'cost_price', 'selling_price', 'quantity', 'reorder_level'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Drug name'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'drug_type': forms.Select(attrs={'class': 'form-control'}),
            'generic_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Generic name'}),
            'manufacturer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Manufacturer'}),
            'batch_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Batch number'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Auto: 1.5x cost'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
            'reorder_level': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '10'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        cost_price = cleaned_data.get('cost_price')
        selling_price = cleaned_data.get('selling_price')
        quantity = cleaned_data.get('quantity')
        
        # Auto-calculate selling price if not set
        if cost_price and (not selling_price or selling_price == 0):
            cleaned_data['selling_price'] = cost_price * 1.5
        
        # Validate quantity
        if quantity and quantity < 0:
            raise forms.ValidationError("Quantity cannot be negative")
        
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

# ============ USER REGISTRATION FORM ============
class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES, required=True)
    phone_number = forms.CharField(max_length=20, required=False)
    address = forms.CharField(widget=forms.Textarea, required=False)
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password1', 'password2']
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        
        if commit:
            user.save()
            UserProfile.objects.create(
                user=user,
                role=self.cleaned_data['role'],
                phone_number=self.cleaned_data.get('phone_number', ''),
                address=self.cleaned_data.get('address', '')
            )
        return user
