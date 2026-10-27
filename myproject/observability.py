"""Request logging and the /health/ endpoint."""
import json
import logging
import os
import time
import uuid
from collections import deque

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import mongo

logger = logging.getLogger('mj.requests')

# The latest requests handled by this server process, shown on Dashboard → System.
RECENT_REQUESTS = deque(maxlen=200)
QUIET_PREFIXES = ('/static/', '/media/', '/favicon')
STARTED_AT = timezone.now()


class RequestLogMiddleware:
    """Logs one JSON line per request (method, path, status, duration, user) and adds an X-Request-ID."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        request.request_id = request.headers.get('X-Request-ID', '')[:64] or uuid.uuid4().hex[:16]
        response = self.get_response(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response['X-Request-ID'] = request.request_id
        response['Server-Timing'] = f'app;dur={duration_ms}'

        user = getattr(request, 'user', None)
        entry = {
            'time': timezone.now().isoformat(timespec='seconds'), 'request_id': request.request_id,
            'method': request.method, 'path': request.path, 'status': response.status_code,
            'duration_ms': duration_ms, 'user': user.username if user and user.is_authenticated else None,
            'ip': request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0],
        }
        if not request.path.startswith(QUIET_PREFIXES):
            RECENT_REQUESTS.appendleft(entry)
            level = logging.ERROR if response.status_code >= 500 else (
                logging.WARNING if response.status_code >= 400 else logging.INFO)
            logger.log(level, json.dumps(entry))
        return response

    def process_exception(self, request, exception):
        logger.exception('Unhandled error in %s %s (request %s)', request.method, request.path,
                         getattr(request, 'request_id', '-'))


@never_cache
@require_GET
def health(request):
    """Liveness and dependency check for uptime monitors: 200 when the store can serve, 503 otherwise."""
    checks = {}
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        checks['database'] = {'ok': True, 'engine': connection.vendor,
                              'latency_ms': round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:  # Any database failure means the store can't serve.
        checks['database'] = {'ok': False, 'error': str(exc)[:200]}

    if checks['database']['ok']:
        try:
            from django.db.migrations.executor import MigrationExecutor

            executor = MigrationExecutor(connection)
            checks['database']['pending_migrations'] = len(
                executor.migration_plan(executor.loader.graph.leaf_nodes()))
        except Exception as exc:  # Report, don't fail the health check.
            checks['database']['pending_migrations'] = f'unknown ({exc.__class__.__name__})'
    if settings.DATABASE_URL:
        from .vercel import SETUP

        checks['database']['setup'] = SETUP
    host = settings.DATABASES['default'].get('HOST', '')
    if host[:1].isalpha():
        # e.g. "us-east-1" from ep-name-pooler.us-east-1.aws.neon.tech: keep the app near its database.
        checks['database']['region'] = host.split('.')[1] if host.count('.') >= 2 else ''
    checks['database']['app_region'] = os.environ.get('VERCEL_REGION', '')

    mongo_ok, mongo_detail = mongo.ping()
    checks['mongodb'] = {'ok': mongo_ok, 'detail': mongo_detail}

    from assistant import providers

    config = providers.resolve()
    checks['assistant'] = {'ok': True, 'engine': config.label if config else 'Smart assistant (rule-based)'}
    paused = {name: reason for name in providers.PROVIDER_LABELS if (reason := providers.paused(name))}
    if paused:
        checks['assistant']['paused'] = paused

    healthy = checks['database']['ok'] and checks['database'].get('pending_migrations', 0) == 0
    status = 'ok' if healthy and mongo_ok is not False else ('degraded' if healthy else 'down')
    return JsonResponse({
        'status': status,
        **({} if healthy else {'code': 'WEB-503'}),
        'checks': checks,
        'version': (settings.GIT_COMMIT or 'dev')[:7],
        'started_at': STARTED_AT.isoformat(timespec='seconds'),
        'time': timezone.now().isoformat(timespec='seconds'),
    }, status=200 if healthy else 503)
