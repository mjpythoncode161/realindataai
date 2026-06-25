from django.core.management.base import BaseCommand

from saas.services import seed_default_plans


class Command(BaseCommand):
    help = "Seed Basic, Premium, and Diamond subscription plans."

    def handle(self, *args, **options):
        seed_default_plans()
        self.stdout.write(self.style.SUCCESS("SaaS plans seeded: Basic, Premium, Diamond."))
