from django.core.management.base import BaseCommand
from django.utils import timezone
from stock.views import generate_report_data, send_report_email
from stock.models import Report, User

class Command(BaseCommand):
    help = 'Send daily report email at midnight'

    def handle(self, *args, **options):
        self.stdout.write('Generating daily report...')
        
        # Generate report
        report_data = generate_report_data('daily')
        
        # Send email
        success = send_report_email(report_data, 'kiyimbahenry314@gmail.com', 'daily')
        
        if success:
            # Save report
            admin_user = User.objects.filter(is_superuser=True).first()
            Report.objects.create(
                report_type='daily',
                data=report_data,
                generated_by=admin_user,
                sent_to_email=True,
                email_sent_at=timezone.now()
            )
            self.stdout.write(self.style.SUCCESS('✅ Daily report sent successfully!'))
        else:
            self.stdout.write(self.style.
