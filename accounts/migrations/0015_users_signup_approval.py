from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_users_role_followup"),
    ]

    operations = [
        migrations.AddField(
            model_name="users",
            name="signup_approved",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="users",
            name="signup_approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="users",
            name="signup_approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="signup_approvals_given",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
