from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('stock', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='invoice',
            name='notes',
        ),
        migrations.AddField(
            model_name='invoice',
            name='total_cost',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Total cost of all items on this invoice', max_digits=12),
        ),
    ]
