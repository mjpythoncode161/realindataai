from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0029_bookingagentsettings"),
        ("accounts", "0016_users_roles"),
    ]

    operations = [
        migrations.CreateModel(
            name="Lead",
            fields=[
                ("lead_id", models.AutoField(primary_key=True, serialize=False)),
                ("full_name", models.CharField(max_length=150)),
                ("phone", models.CharField(max_length=15)),
                ("email", models.EmailField(blank=True, default="", max_length=255)),
                ("plot_interest", models.CharField(blank=True, default="", max_length=200)),
                ("budget", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("CALL", "Phone Call"),
                            ("WALK_IN", "Walk-in"),
                            ("WEBSITE", "Website"),
                            ("REFERRAL", "Referral"),
                            ("SOCIAL", "Social Media"),
                            ("OTHER", "Other"),
                        ],
                        default="CALL",
                        max_length=20,
                    ),
                ),
                ("occupation", models.CharField(blank=True, default="", max_length=200)),
                ("present_address", models.TextField(blank=True, default="")),
                ("aadhar_number", models.CharField(blank=True, default="", max_length=12)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("NEW", "New"),
                            ("CONTACTED", "Contacted"),
                            ("IN_PROGRESS", "In Progress"),
                            ("CONFIRMED", "Confirmed"),
                            ("CLOSED_LOST", "Closed (Lost)"),
                        ],
                        default="NEW",
                        max_length=20,
                    ),
                ),
                ("next_follow_up_date", models.DateField(blank=True, null=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_leads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="leads_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "converted_customer",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="source_lead",
                        to="accounts.customer",
                    ),
                ),
                (
                    "p_id",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="leads",
                        to="bookings.project",
                    ),
                ),
            ],
            options={
                "db_table": "leads",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="LeadActivity",
            fields=[
                ("activity_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "activity_type",
                    models.CharField(
                        choices=[
                            ("CALL", "Phone Call"),
                            ("VISIT", "Site Visit"),
                            ("NOTE", "Note"),
                            ("STATUS", "Status Update"),
                        ],
                        default="NOTE",
                        max_length=20,
                    ),
                ),
                ("note", models.TextField()),
                ("next_follow_up_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lead_activities",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lead",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activities",
                        to="accounts.lead",
                    ),
                ),
            ],
            options={
                "db_table": "lead_activities",
                "ordering": ["-created_at"],
            },
        ),
    ]
