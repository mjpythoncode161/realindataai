from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0028_bookingmaster_kgp_completed"),
    ]

    operations = [
        migrations.CreateModel(
            name="BookingAgentSettings",
            fields=[
                ("settings_id", models.AutoField(primary_key=True, serialize=False)),
                ("enable_manager", models.BooleanField(default=True)),
                ("enable_executive", models.BooleanField(default=True)),
                ("enable_telecaller", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Booking agent settings",
                "verbose_name_plural": "Booking agent settings",
                "db_table": "booking_agent_settings",
            },
        ),
    ]
