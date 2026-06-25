from django.core.management.base import BaseCommand
from django.db.models import Q

from accounts.models import ActivityLog, Lead, Users
from bookings.models import BookingAgentSettings, BookingMaster, Project
from saas.models import Organization, OrganizationMembership


class Command(BaseCommand):
    help = "Backfill organization FK on bookings, leads, settings, and orphan users."

    def handle(self, *args, **options):
        default_org = Organization.objects.order_by("org_id").first()
        if not default_org:
            self.stderr.write("No organizations found. Run setup_default_tenant first.")
            return

        # Projects without org → default (legacy) or skip
        orphan_projects = Project.objects.filter(organization__isnull=True)
        n = orphan_projects.update(organization=default_org)
        self.stdout.write(f"Projects linked: {n}")

        # Bookings from project org
        for booking in BookingMaster.objects.filter(organization__isnull=True).select_related("p_id"):
            org = booking.p_id.organization if booking.p_id else default_org
            booking.organization = org or default_org
            booking.save(update_fields=["organization"])
        self.stdout.write("Bookings linked from projects.")

        # Leads
        for lead in Lead.objects.filter(organization__isnull=True).select_related("p_id", "created_by"):
            org = None
            if lead.p_id and lead.p_id.organization_id:
                org = lead.p_id.organization
            elif lead.created_by and lead.created_by.organization_id:
                org = lead.created_by.organization
            lead.organization = org or default_org
            lead.save(update_fields=["organization"])
        self.stdout.write("Leads linked.")

        # Users without org — assign via created_by chain or default
        for user in Users.objects.filter(organization__isnull=True).exclude(is_superuser=True):
            org = default_org
            if user.created_by_id and user.created_by.organization_id:
                org = user.created_by.organization
            user.organization = org
            user.save(update_fields=["organization"])
            OrganizationMembership.objects.get_or_create(
                organization=org, user=user, defaults={"is_owner": False}
            )
        self.stdout.write("Users linked.")

        # Per-org booking settings
        legacy = BookingAgentSettings.objects.filter(organization__isnull=True).first()
        for org in Organization.objects.all():
            settings, created = BookingAgentSettings.objects.get_or_create(
                organization=org,
                defaults={
                    "company_name": org.name,
                    "company_address": legacy.company_address if legacy else "",
                    "company_phone": legacy.company_phone if legacy else "",
                    "company_email": legacy.company_email if legacy else "",
                    "enable_manager": legacy.enable_manager if legacy else True,
                    "enable_executive": legacy.enable_executive if legacy else True,
                    "enable_telecaller": legacy.enable_telecaller if legacy else True,
                },
            )
            if created:
                self.stdout.write(f"  Settings for {org.name}")

        for log in ActivityLog.objects.filter(organization__isnull=True).select_related("user"):
            org = None
            if log.user and log.user.organization_id:
                org = log.user.organization
            log.organization = org or default_org
            log.save(update_fields=["organization"])
        self.stdout.write("Activity logs linked.")

        from tally.models import LedgerMaster, Voucher

        LedgerMaster.objects.filter(organization__isnull=True).update(organization=default_org)
        Voucher.objects.filter(organization__isnull=True).update(organization=default_org)
        self.stdout.write("Tally ledgers and vouchers linked.")

        self.stdout.write(self.style.SUCCESS("Tenant isolation backfill complete."))
