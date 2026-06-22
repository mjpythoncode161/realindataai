from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0027_accountsdebitpayment"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookingmaster",
            name="kgp_completed",
            field=models.BooleanField(
                default=False,
                help_text="Government survey (KGP) completed for this booking.",
            ),
        ),
        migrations.AddField(
            model_name="bookingmaster",
            name="kgp_completed_at",
            field=models.DateField(blank=True, null=True),
        ),
    ]
