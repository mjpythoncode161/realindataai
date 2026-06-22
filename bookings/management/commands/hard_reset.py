from django.core.management.base import BaseCommand
from django.db import connection
from django.contrib.auth import get_user_model
from bookings.models import Project, AgentMaster, BookingMaster, BookingItem, BalanceMaster, ReceiptMaster
from accounts.models import Customer
import os

class Command(BaseCommand):
    help = "Hard resets the database: truncates all tables and resets auto-increment to 1 while preserving the admin."

    def handle(self, *args, **options):
        User = get_user_model()
        admin_email = "admin@admin.com"
        
        self.stdout.write(self.style.WARNING("Starting Hard Reset..."))

        # 1. Backup admin data
        admin = User.objects.filter(email=admin_email).first()
        admin_fields = {}
        if admin:
            admin_fields = {
                'password': admin.password,
                'is_superuser': admin.is_superuser,
                'username': admin.username,
                'is_staff': admin.is_staff,
                'is_active': admin.is_active,
                'full_name': admin.full_name,
                'email': admin.email,
                'phone': admin.phone,
                'role': admin.role,
            }

        # 2. Truncate tables
        tables = [
            "booking_item", "balance_master", "receipt_master", 
            "booking_master", "agent_master", "project", "customers", "users"
        ]

        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            for table in tables:
                self.stdout.write(f"Truncating {table}...")
                cursor.execute(f"TRUNCATE TABLE {table};")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

        # 3. Restore admin
        if admin_fields:
            self.stdout.write("Restoring admin account as ID 1...")
            new_admin = User(u_id=1, **admin_fields)
            new_admin.save()
        else:
            self.stdout.write("Creating fresh admin account as ID 1...")
            User.objects.create_superuser(
                u_id=1,
                email=admin_email,
                password="123",
                username="admin",
                full_name="Administrator",
                phone="0000000000",
                role="admin"
            )

        self.stdout.write(self.style.SUCCESS("SUCCESS: Database fully reset. Admin is ID 1. Next record will be ID 2."))
