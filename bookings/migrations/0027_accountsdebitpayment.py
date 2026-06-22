from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_accounts_debits(apps, schema_editor):
    AgentMaster = apps.get_model("bookings", "AgentMaster")
    AccountsDebitPayment = apps.get_model("bookings", "AccountsDebitPayment")
    from django.utils import timezone

    today = timezone.localdate()
    for agent in AgentMaster.objects.filter(role="accounts"):
        if agent.commission_percentage and agent.commission_percentage > 0:
            AccountsDebitPayment.objects.create(
                agent_master_id=agent.am_id,
                debit_type="COMMISSION",
                amount=agent.commission_percentage,
                payment_date=agent.effective_date or today,
                payment_method=agent.payment_method or "CASH",
                remarks="Migrated from accounts profile",
            )
        if agent.security_amount and agent.security_amount > 0:
            AccountsDebitPayment.objects.create(
                agent_master_id=agent.am_id,
                debit_type="SECURITY",
                amount=agent.security_amount,
                payment_date=agent.effective_date or today,
                payment_method=agent.payment_method or "CASH",
                remarks="Migrated from accounts profile",
            )


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0026_agentmaster_payment_method"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountsDebitPayment",
            fields=[
                ("adp_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "debit_type",
                    models.CharField(
                        choices=[
                            ("COMMISSION", "Commission (Debit)"),
                            ("SECURITY", "Security Deposit (Debit)"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14),
                ),
                ("payment_date", models.DateField()),
                (
                    "payment_method",
                    models.CharField(
                        choices=[
                            ("CASH", "Cash"),
                            ("BANK_TRANSFER", "Bank Transfer"),
                            ("UPI", "UPI"),
                            ("CHEQUE", "Cheque"),
                        ],
                        default="CASH",
                        max_length=20,
                    ),
                ),
                ("remarks", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "agent_master",
                    models.ForeignKey(
                        limit_choices_to={"role": "accounts"},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="debit_payments",
                        to="bookings.agentmaster",
                    ),
                ),
            ],
            options={
                "db_table": "accounts_debit_payment",
                "ordering": ["payment_date", "adp_id"],
            },
        ),
        migrations.RunPython(migrate_legacy_accounts_debits, migrations.RunPython.noop),
    ]
