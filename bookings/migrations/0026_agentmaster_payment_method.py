from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0025_agentmaster_effective_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentmaster',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[
                    ('CASH', 'Cash'),
                    ('BANK_TRANSFER', 'Bank Transfer'),
                    ('UPI', 'UPI'),
                    ('CHEQUE', 'Cheque'),
                ],
                default='',
                max_length=20,
            ),
        ),
    ]
