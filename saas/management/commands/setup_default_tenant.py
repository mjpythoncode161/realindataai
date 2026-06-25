from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Users
from bookings.models import Project
from saas.models import Organization, OrganizationMembership, SubscriptionPlan
from saas.services import seed_default_plans


class Command(BaseCommand):
    help = "Assign existing data to a default organization (one-time migration helper)."

    def handle(self, *args, **options):
        seed_default_plans()
        diamond = SubscriptionPlan.objects.get(tier=SubscriptionPlan.Tier.DIAMOND)

        admin_user = Users.objects.filter(is_superuser=True).first()
        if not admin_user:
            admin_user = Users.objects.order_by("u_id").first()
        if not admin_user:
            self.stdout.write(self.style.WARNING("No users found — skip org migration."))
            return

        org, created = Organization.objects.get_or_create(
            slug="default",
            defaults={
                "name": "Land Link Default",
                "owner": admin_user,
                "plan": diamond,
                "status": Organization.Status.ACTIVE,
                "subscription_started_at": timezone.now(),
            },
        )
        if created or not org.subscription_ends_at:
            org.activate_subscription(diamond, period_days=3650)

        Users.objects.filter(organization__isnull=True).update(organization=org)
        Project.objects.filter(organization__isnull=True).update(organization=org)

        for user in Users.objects.filter(organization=org):
            OrganizationMembership.objects.get_or_create(
                organization=org,
                user=user,
                defaults={"is_owner": user.u_id == admin_user.u_id},
            )

        self.stdout.write(
            self.style.SUCCESS(f"Default organization ready: {org.name} (id={org.org_id})")
        )
