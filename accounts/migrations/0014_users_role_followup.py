from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_users_trial_and_company"),
    ]

    operations = [
        migrations.AlterField(
            model_name="users",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "Admin"),
                    ("customer", "Customer"),
                    ("manager", "Manager"),
                    ("executive", "Executive"),
                    ("telecaller", "Telecaller"),
                    ("accounts", "Accounts"),
                    ("followup", "Followup"),
                ],
                default="customer",
                max_length=10,
            ),
        ),
    ]
