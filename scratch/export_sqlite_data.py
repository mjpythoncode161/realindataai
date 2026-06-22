import io
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crm1.settings_sqlite")

import django

django.setup()

from django.core.management import call_command

output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sqlite_data.json")
buffer = io.StringIO()
call_command(
    "dumpdata",
    natural_foreign=True,
    natural_primary=True,
    exclude=["contenttypes", "auth.permission"],
    indent=2,
    stdout=buffer,
)
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write(buffer.getvalue())

print(f"Exported to {output_path} ({os.path.getsize(output_path)} bytes)")
