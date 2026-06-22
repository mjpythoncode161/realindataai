# Generated manually for Land Link trial signups

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_customer_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="users",
            name="company_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="users",
            name="is_trial_account",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="users",
            name="trial_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="users",
            name="trial_ends_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
