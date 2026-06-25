from django.core.management.base import BaseCommand

from accounts.models import Users


class Command(BaseCommand):
    help = "Grant platform super admin (is_superuser + is_staff) to a user by email or username."

    def add_arguments(self, parser):
        parser.add_argument("identifier", help="User email, phone, or username")
        parser.add_argument(
            "--clear-org",
            action="store_true",
            help="Remove organization link so user has full platform access without tenant limits",
        )

    def handle(self, *args, **options):
        raw = options["identifier"].strip()
        user = Users.objects.filter(email__iexact=raw).first()
        if not user:
            user = Users.objects.filter(username=raw).first()
        if not user and raw.isdigit():
            user = Users.objects.filter(phone=raw[-10:]).first()
        if not user:
            self.stderr.write(self.style.ERROR(f"No user found for: {raw}"))
            return

        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        update_fields = ["is_superuser", "is_staff", "is_active"]

        if options["clear_org"]:
            user.organization = None
            update_fields.append("organization")

        user.save(update_fields=update_fields)
        self.stdout.write(
            self.style.SUCCESS(
                f"Super admin granted to {user.full_name} ({user.email}). "
                f"Login and open /saas/platform/"
            )
        )
