from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tally", "0002_ledgermaster_is_system_alter_ledgermaster_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="voucherentry",
            name="narration",
            field=models.TextField(blank=True, default=""),
        ),
    ]
