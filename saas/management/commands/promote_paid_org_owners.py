from django.core.management.base import BaseCommand

from saas.models import Organization
from saas.services import promote_org_owner_to_admin


class Command(BaseCommand):
    help = "Grant full admin access to owners of all active paid organizations."

    def handle(self, *args, **options):
        count = 0
        for org in Organization.objects.filter(status=Organization.Status.ACTIVE).select_related("owner"):
            if org.is_subscription_active:
                promote_org_owner_to_admin(org)
                count += 1
                self.stdout.write(f"  ✓ {org.name} — owner {org.owner.email} → admin")
        self.stdout.write(self.style.SUCCESS(f"Updated {count} organization owner(s)."))
