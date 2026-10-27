"""Start-up for Vercel, whose code folder is read-only and only /tmp is writable.

Copies the committed product photos to MEDIA_ROOT. Then:

- With DATABASE_URL (Postgres, shared by every instance): applies migrations, loads the
  product catalog (deploy/catalog.json) into an empty store and creates the administrator
  from DJANGO_ADMIN_USERNAME / DJANGO_ADMIN_PASSWORD / DJANGO_ADMIN_EMAIL if missing.
  An advisory lock makes sure only one instance does this at a time.
- Without it: copies the demo database (deploy/demo.sqlite3) to /tmp. Each instance gets
  its own copy, so sign-ins, sign-ups and tickets are not shared and reset on cold starts.
"""
import logging
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)

CATALOG_FIXTURE = Path(settings.BASE_DIR) / 'deploy' / 'catalog.json'
SETUP_LOCK_ID = 7_302_025  # Any constant shared by all instances.


def prepare():
    if not settings.ON_VERCEL:
        return
    media_root = Path(settings.MEDIA_ROOT)
    if not media_root.exists() and Path(settings.MEDIA_SOURCE).exists():
        try:
            shutil.copytree(settings.MEDIA_SOURCE, media_root, dirs_exist_ok=True)
        except OSError:
            logger.exception('Could not copy product photos to %s', media_root)
    if settings.DATABASE_URL:
        try:
            setup_database()
        except Exception:  # Keep serving; the health check and logs show the problem.
            logger.exception('Database setup failed')
        return
    database = Path(settings.DATABASES['default']['NAME'])
    if not database.exists():
        if settings.DEMO_DATABASE.exists():
            shutil.copyfile(settings.DEMO_DATABASE, database)
        else:
            logger.warning('No DATABASE_URL and no %s; starting with an empty store.', settings.DEMO_DATABASE)
        # Brings the demo copy up to date with any migrations added since it was built.
        call_command('migrate', interactive=False, verbosity=0)


def setup_database():
    """Migrate, load the catalog into an empty store and create the admin (safe to run on every start)."""
    from django.db import connection, transaction

    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [SETUP_LOCK_ID])
                if not cursor.fetchone()[0]:
                    return  # Another instance is setting up right now.
        call_command('migrate', interactive=False, verbosity=0)

        from catalog.models import Product

        if not Product.objects.exists() and CATALOG_FIXTURE.exists():
            call_command('loaddata', str(CATALOG_FIXTURE), verbosity=0)
            logger.warning('Loaded the product catalog into the new database.')
        ensure_admin()


def ensure_admin():
    """Create the administrator account from environment variables if it doesn't exist yet."""
    from django.contrib.auth import get_user_model

    username = os.environ.get('DJANGO_ADMIN_USERNAME', '').strip()
    password = os.environ.get('DJANGO_ADMIN_PASSWORD', '')
    if not (username and password):
        return
    User = get_user_model()
    if User.objects.filter(username=username).exists():
        return  # Never overwrite a password someone may have changed.
    User.objects.create_superuser(
        username=username, password=password, email=os.environ.get('DJANGO_ADMIN_EMAIL', ''),
        role=User.Role.ADMIN, first_name='Store', last_name='Admin',
    )
    logger.warning('Created administrator account %s.', username)
