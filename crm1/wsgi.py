"""
WSGI config for crm1 project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crm1.settings")

application = get_wsgi_application()
