from django.db import migrations
from decimal import Decimal
from datetime import timedelta

def migrate_credit_receipts(apps, schema_editor):
    """Create CreditSale records from existing credit receipts"""
    Receipt = apps.get_model('stock', 'Receipt')
    CreditSale = apps.get_model('stock', 'CreditSale')
    CreditPayment = apps.get_model('stock', 'CreditPayment')
    User = apps.get_model('auth', 'User')
    
    # Get the admin user or first user as fallback
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        admin_user = User.objects.first()
    
    if not admin_user:
        print("⚠️ No user found! Skipping credit receipt migration.")
        return
    
    # Find all receipts that are credit but don't have a credit_sale linked
    credit_receipts = Receipt.objects.filter(
        is_credit=True,
        credit_sale__isnull=True
    )
    
    if not credit_receipts.exists():
        print("✅ No credit receipts to migrate.")
        return
    
    created_count = 0
    for receipt in credit_receipts:
        # Calculate remaining balance
        remaining = receipt.total_amount - receipt.amount_paid
        
        # Create CreditSale record
        credit_sale = CreditSale.objects.create(
            credit_receipt_number=f"CR-{receipt.created_at.strftime('%Y%m%d')}-{created_count + 1:04d}",
            customer_name=receipt.customer_name or "Walk-in Customer",
            customer_phone=receipt.customer_phone or "",
            total_amount=receipt.total_amount,
            amount_paid=receipt.amount_paid,
            remaining_balance=max(remaining, Decimal('0.00')),
            payment_method=receipt.payment_method,
            items=receipt.items,
            due_date=receipt.created_at.date() + timedelta(days=30),
            status='paid' if remaining <= 0 else 'partial',
            created_by=admin_user,
            created_at=receipt.created_at,
            updated_at=receipt.created_at
        )
        
        # Link the receipt to the credit sale
        receipt.credit_sale = credit_sale
        receipt.save()
        
        created_count += 1
        
        # Create CreditPayment record if payment was made
        if receipt.amount_paid > 0:
            CreditPayment.objects.create(
                credit_sale=credit_sale,
                amount=receipt.amount_paid,
                payment_method=receipt.payment_method,
                reference=f"Initial payment from receipt {receipt.receipt_number}",
                created_by=admin_user,
                created_at=receipt.created_at
            )
        
        print(f"✅ Migrated receipt {receipt.receipt_number}")
    
    print(f"✅ Created {created_count} CreditSale records from existing receipts")

def reverse_migrate_credit_receipts(apps, schema_editor):
    """Remove CreditSale records created from receipts (rollback)"""
    CreditSale = apps.get_model('stock', 'CreditSale')
    Receipt = apps.get_model('stock', 'Receipt')
    
    # Find CreditSales that have no payments (created from receipts)
    credit_sales = CreditSale.objects.filter(payments__isnull=True)
    
    # Unlink receipts
    for credit_sale in credit_sales:
        Receipt.objects.filter(credit_sale=credit_sale).update(credit_sale=None)
    
    # Delete the credit sales
    count = credit_sales.count()
    credit_sales.delete()
    
    print(f"✅ Rolled back {count} credit sale migrations")

class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0014_dosageform_receipt_cleared_by_receipt_cleared_date_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_credit_receipts, reverse_migrate_credit_receipts),
    ]
