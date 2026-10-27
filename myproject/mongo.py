"""MongoDB storage for chat transcripts and customer feedback.

Set MONGODB_URI (e.g. a free MongoDB Atlas cluster) to turn it on. Every chat
turn is written to the `chats` collection and every rating to `feedback`. The
SQL database still keeps chat history for the widget, so the site works the
same when MongoDB is not configured or unreachable: failed writes are logged
and MongoDB is skipped for a minute before trying again.
"""
import logging
import time

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = 60
_state = {'client': None, 'down_until': 0.0}


def is_configured():
    return bool(settings.MONGODB_URI)


def _database():
    if not is_configured() or time.monotonic() < _state['down_until']:
        return None
    if _state['client'] is None:
        from pymongo import MongoClient

        _state['client'] = MongoClient(
            settings.MONGODB_URI, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000,
            socketTimeoutMS=3000, appname='mj-store',
        )
    return _state['client'][settings.MONGODB_DB]


def _failed(action, exc):
    logger.warning('MongoDB %s failed (%s); using SQL only for %ss.', action, exc, RETRY_AFTER_SECONDS)
    _state['down_until'] = time.monotonic() + RETRY_AFTER_SECONDS


def insert(collection, document):
    """Insert a document; returns True if it was stored in MongoDB."""
    from pymongo.errors import PyMongoError

    db = _database()
    if db is None:
        return False
    try:
        db[collection].insert_one({**document, 'created_at': timezone.now()})
        return True
    except PyMongoError as exc:
        _failed(f'insert into {collection}', exc)
        return False


def find(collection, query=None, limit=50):
    """Most recent documents first; [] when MongoDB is unavailable."""
    from pymongo.errors import PyMongoError

    db = _database()
    if db is None:
        return []
    try:
        return list(db[collection].find(query or {}, {'_id': 0}).sort('created_at', -1).limit(limit))
    except PyMongoError as exc:
        _failed(f'read from {collection}', exc)
        return []


def ping():
    """(ok, detail) for the health check. ok is None when MongoDB is not configured."""
    from pymongo.errors import PyMongoError

    if not is_configured():
        return None, 'Not configured (set MONGODB_URI)'
    db = _database()
    if db is None:
        return False, 'Unreachable recently; retrying shortly'
    started = time.perf_counter()
    try:
        db.command('ping')
    except PyMongoError as exc:
        _failed('ping', exc)
        return False, str(exc)[:200]
    return True, f'{(time.perf_counter() - started) * 1000:.0f} ms'


def counts():
    """Document counts per collection for the System page ({} when unavailable)."""
    from pymongo.errors import PyMongoError

    db = _database()
    if db is None:
        return {}
    try:
        return {name: db[name].estimated_document_count() for name in ('chats', 'feedback')}
    except PyMongoError as exc:
        _failed('count', exc)
        return {}
