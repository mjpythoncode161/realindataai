# Generated manually for tenant isolation

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("saas", "0001_initial"),
        ("tally", "0003_voucherentry_narration"),
    ]

    operations = [
        migrations.AddField(
            model_name="ledgermaster",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tally_ledgers",
                to="saas.organization",
            ),
        ),
        migrations.AddField(
            model_name="voucher",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tally_vouchers",
                to="saas.organization",
            ),
        ),
        migrations.AlterField(
            model_name="ledgermaster",
            name="name",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterUniqueTogether(
            name="ledgermaster",
            unique_together={("organization", "name")},
        ),
        migrations.AlterField(
            model_name="voucher",
            name="voucher_no",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterUniqueTogether(
            name="voucher",
            unique_together={("organization", "voucher_no")},
        ),
    ]
