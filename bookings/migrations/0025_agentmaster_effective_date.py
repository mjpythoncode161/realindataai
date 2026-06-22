from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0024_fix_commission_percentage_max_digits'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentmaster',
            name='effective_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
