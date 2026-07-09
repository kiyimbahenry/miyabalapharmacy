from django.core.management.base import BaseCommand
from stock.models import Category

class Command(BaseCommand):
    help = 'Add default categories to the database'

    def handle(self, *args, **kwargs):
        categories = [
            'Antibiotic',
            'Painkiller',
            'Anti-fungals',
            'Beauty and Cosmetics',
            'Neuro Care',
            'Anti-diabetics',
            'Anti-hypertensives',
            'Cough, Cold and Flu',
            'Supplements',
            'PUD',
            'Vitamins and Minerals',
            'Anti-infectives'
        ]

        created_count = 0
        for category_name in categories:
            category, created = Category.objects.get_or_create(name=category_name)
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'Created category: {category_name}'))
            else:
                self.stdout.write(self.style.WARNING(f'Category already exists: {category_name}'))

        self.stdout.write(self.style.SUCCESS(f'Successfully created {created_count} new categories'))
