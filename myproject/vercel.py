"""Start-up for Vercel, whose code folder is read-only and only /tmp is writable.

Copies the committed product photos to MEDIA_ROOT. Then:

- With DATABASE_URL (Postgres, shared by every instance): applies migrations, loads the
  product catalog (deploy/catalog.json) into an empty store and creates the administrator
  from DJANGO_ADMIN_USERNAME / DJANGO_ADMIN_PASSWORD / DJANGO_ADMIN_EMAIL if missing.
  Each migration commits on its own, so if a cold start is cut short the next one carries
  on. An advisory lock on the direct (unpooled) connection lets one instance at a time do it.
  The outcome is shown at /health/ under "setup".
- Without it: copies the demo database (deploy/demo.sqlite3) to /tmp. Each instance gets
  its own copy, so sign-ins, sign-ups and tickets are not shared and reset on cold starts.
"""
import logging
import os
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)

CATALOG_FIXTURE = Path(settings.BASE_DIR) / 'deploy' / 'catalog.json'
SETUP_LOCK_ID = 7_302_025  # Any constant shared by all instances.
# Direct connection strings set by Vercel's Neon/Postgres integrations (advisory locks need one).
UNPOOLED_URL_VARS = ('DATABASE_URL_UNPOOLED', 'POSTGRES_URL_NON_POOLING')

SETUP = {'status': 'not run', 'error': '', 'seconds': None}


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
        run_setup()
        return
    database = Path(settings.DATABASES['default']['NAME'])
    if not database.exists():
        if settings.DEMO_DATABASE.exists():
            shutil.copyfile(settings.DEMO_DATABASE, database)
        else:
            logger.warning('No DATABASE_URL and no %s; starting with an empty store.', settings.DEMO_DATABASE)
        # Brings the demo copy up to date with any migrations added since it was built.
        call_command('migrate', interactive=False, verbosity=0)


def run_setup():
    started = time.monotonic()
    try:
        SETUP.update(status=setup_database(), error='')
    except Exception as exc:  # Keep serving; /health/ and the logs show the problem.
        logger.exception('Database setup failed')
        SETUP.update(status='failed', error=f'{exc.__class__.__name__}: {exc}'[:500])
    SETUP['seconds'] = round(time.monotonic() - started, 1)
    logger.warning('Database setup: %s (%ss)', SETUP['status'], SETUP['seconds'])


def _take_lock():
    """A direct connection holding the setup lock; None if no lock is available; False if taken."""
    url = next((os.environ[name] for name in UNPOOLED_URL_VARS if os.environ.get(name)), '')
    if not url:
        return None
    import psycopg

    lock = psycopg.connect(url, autocommit=True, connect_timeout=15)
    if lock.execute('SELECT pg_try_advisory_lock(%s)', [SETUP_LOCK_ID]).fetchone()[0]:
        return lock  # Released when this connection closes, even if the instance is killed.
    lock.close()
    return False


def setup_database():
    """Migrate, load the catalog into an empty store and create the admin (safe to run on every start)."""
    lock = _take_lock()
    if lock is False:
        return 'skipped: another instance is setting up the database'
    try:
        call_command('migrate', interactive=False, verbosity=0)

        from catalog.models import Product

        loaded = ''
        if not Product.objects.exists() and CATALOG_FIXTURE.exists():
            call_command('loaddata', str(CATALOG_FIXTURE), verbosity=0)
            loaded = ', catalog loaded'
        return f'done{loaded}{ensure_admin()}'
    finally:
        if lock:
            lock.close()


def ensure_admin():
    """Create the administrator account from environment variables if it doesn't exist yet."""
    from django.contrib.auth import get_user_model

    username = os.environ.get('DJANGO_ADMIN_USERNAME', '').strip()
    password = os.environ.get('DJANGO_ADMIN_PASSWORD', '')
    if not (username and password):
        return ', no admin configured (set DJANGO_ADMIN_USERNAME and DJANGO_ADMIN_PASSWORD)'
    User = get_user_model()
    if User.objects.filter(username=username).exists():
        return ''  # Never overwrite a password someone may have changed.
    User.objects.create_superuser(
        username=username, password=password, email=os.environ.get('DJANGO_ADMIN_EMAIL', ''),
        role=User.Role.ADMIN, first_name='Store', last_name='Admin',
    )
    logger.warning('Created administrator account %s.', username)
    return ', admin created'
