"""Start-up for Vercel, whose code folder is read-only and only /tmp is writable.

Copies the committed product photos to MEDIA_ROOT and, when no DATABASE_URL is set,
the demo database (deploy/demo.sqlite3) to /tmp. Both are per instance, so the demo
data resets whenever Vercel starts a fresh instance.
"""
import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)


def prepare():
    if not settings.ON_VERCEL:
        return
    media_root = Path(settings.MEDIA_ROOT)
    if not media_root.exists() and Path(settings.MEDIA_SOURCE).exists():
        shutil.copytree(settings.MEDIA_SOURCE, media_root)
    if settings.DATABASE_URL:
        return  # Run `manage.py migrate` against the real database when deploying.
    database = Path(settings.DATABASES['default']['NAME'])
    if not database.exists():
        if settings.DEMO_DATABASE.exists():
            shutil.copyfile(settings.DEMO_DATABASE, database)
        else:
            logger.warning('No DATABASE_URL and no %s; starting with an empty store.', settings.DEMO_DATABASE)
        # Brings the demo copy up to date with any migrations added since it was built.
        call_command('migrate', interactive=False, verbosity=0)
