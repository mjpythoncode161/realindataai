"""One-off settings module to read legacy SQLite data during migration."""
from .settings import *  # noqa: F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'u673831287_two_db',
        'USER': 'u673831287_two_db',  # replace if your MySQL username is different
        'PASSWORD': 'v~lM*SY?!6O',
        'HOST': '92.113.22.3',
        'PORT': '3306',
    }
}
