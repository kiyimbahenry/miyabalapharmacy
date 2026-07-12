# stock/migrations/0012_create_default_categories.py
from django.db import migrations

def create_categories(apps, schema_editor):
    Category = apps.get_model('stock', 'Category')
    categories = [
        'Antibiotic',
        'Anti-hypertensives',
        'Anti-diabetics',
        'Anti-Ulcer',
        'Cough and Flu',
        'Neuro Care',
        'Anti-fungals',
        'Anti-infectives',
        'Painkillers',
        'Beauty and Cosmetics',
        'Vitamins and Minerals',
        'Supplements'
    ]
    for name in categories:
        Category.objects.get_or_create(name=name)

def reverse_func(apps, schema_editor):
    # Optional: delete them if you want to rollback
    Category = apps.get_model('stock', 'Category')
    Category.objects.filter(name__in=[
        'Antibiotic', 'Anti-hypertensives', 'Anti-diabetics',
        'Anti-Ulcer', 'Cough and Flu', 'Neuro Care',
        'Anti-fungals', 'Anti-infectives', 'Painkillers',
        'Beauty and Cosmetics', 'Vitamins and Minerals', 'Supplements'
    ]).delete()

class Migration(migrations.Migration):
    dependencies = [
        ('stock', '0011_merge_20260712'),  # Adjust to your last migration
    ]
    operations = [
        migrations.RunPython(create_categories, reverse_func),
    ]
