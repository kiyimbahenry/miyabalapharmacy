from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from .models import Receipt, CreditSale, CreditPayment

@receiver(post_save, sender=Receipt)
def create_credit_sale_from_receipt(sender, instance, created, **kwargs):
    """Auto-create CreditSale when a credit receipt is saved"""
    if created and instance.payment_method.lower() == 'credit' and not instance.credit_sale:
        remaining = instance.total_amount - instance.amount_paid
        
        credit_sale = CreditSale.objects.create(
            credit_receipt_number=f"CR-{instance.created_at.strftime('%Y%m%d')}-{CreditSale.objects.count() + 1:04d}",
            customer_name=instance.customer_name or "Walk-in Customer",
            customer_phone=instance.customer_phone or "",
            total_amount=instance.total_amount,
            amount_paid=instance.amount_paid,
            remaining_balance=max(remaining, Decimal('0.00')),
            payment_method=instance.payment_method,
            items=instance.items,
            due_date=instance.created_at.date() + timedelta(days=30),
            status=(
                'paid' if instance.amount_paid >= instance.total_amount
                else 'partial' if instance.amount_paid > 0
                else 'pending'
            ),
            created_by=instance.created_by,
            created_at=instance.created_at
        )
        
        # Link receipt to credit sale
        instance.credit_sale = credit_sale
        instance.is_credit = True
        instance.save()
        
        # If payment was made, create CreditPayment
        if instance.amount_paid > 0:
            CreditPayment.objects.create(
                credit_sale=credit_sale,
                amount=instance.amount_paid,
                payment_method=instance.payment_method,
                reference=f"Initial payment from receipt {instance.receipt_number}",
                created_by=instance.created_by,
                created_at=instance.created_at
            )
        
        print(f"✅ Signal created CreditSale: {credit_sale.credit_receipt_number}")
