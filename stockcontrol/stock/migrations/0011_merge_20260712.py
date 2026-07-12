# stock/migrations/0011_merge_20260712.py

from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('stock', '0002_remove_invoice_notes_add_invoice_total_cost'),
        ('stock', '0010_returneddrug'),
    ]

    operations = []
