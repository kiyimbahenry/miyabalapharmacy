from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

# Import your existing functions from views
from stock.views import generate_report_data, send_report_email
from stock.models import Report, User


class Command(BaseCommand):
    help = 'Send daily report email automatically at midnight'

    def add_arguments(self, parser):
        parser.add_argument(
            '--test',
            action='store_true',
            help='Send test report for today (instead of yesterday)',
        )

    def handle(self, *args, **options):
        try:
            self.stdout.write('🔄 Generating daily report...')

            # ================================================================
            # Determine which date to report on
            # ================================================================
            if options.get('test'):
                report_date = timezone.now().date()
                self.stdout.write(f"🔄 TEST MODE: Running report for {report_date}")
            else:
                # Daily report - run for yesterday
                report_date = timezone.now().date() - timedelta(days=1)
                self.stdout.write(f"🔄 Running daily report for {report_date}")

            # ================================================================
            # FIX: Pass report_date to generate_report_data
            # ================================================================
            report_data = generate_report_data('daily', report_date)  # ← CHANGED: Pass report_date

            # REMOVED: report_data['period'] = f"Daily Report - {report_date.strftime('%B %d, %Y')}"
            # The period is now set inside generate_report_data

            # List of recipients
            recipients = ['kiyimbahenry314@gmail.com', 'daveedaviyam@gmail.com']

            # Send email using your existing send_report_email function
            success = send_report_email(report_data, recipients[0], 'daily')

            if success:
                # Save report to database
                admin_user = User.objects.filter(is_superuser=True).first()
                if admin_user:
                    Report.objects.create(
                        report_type='daily',
                        data=report_data,
                        generated_by=admin_user,
                        sent_to_email=True,
                        email_sent_at=timezone.now()
                    )
                else:
                    # If no admin user, save without generated_by
                    Report.objects.create(
                        report_type='daily',
                        data=report_data,
                        sent_to_email=True,
                        email_sent_at=timezone.now()
                    )

                self.stdout.write(
                    self.style.SUCCESS(f'✅ Daily report sent successfully to {", ".join(recipients)} for {report_date}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR('❌ Failed to send daily report')
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error sending daily report: {str(e)}')
            )
            import traceback
            traceback.print_exc()
