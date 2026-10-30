"""Custom HTTP error pages, with their wording taken from the ErrorCode table.

Every page a customer lands on reads its text from `support.ErrorCode` (the same table behind
/support/error-codes/ and /api/error-codes/), so the reference and the real page can never drift
apart, and support staff can reword an error in the Django admin without a deploy.

If the database is the thing that broke (WEB-503), the seed list in `support.help_content` is used
instead, and if even the styled page cannot be rendered, `plain_page()` returns a self-contained
page that needs no template, no static file and no database.
"""
import logging

from django.http import HttpResponse
from django.shortcuts import render
from django.utils.html import escape

logger = logging.getLogger(__name__)

# The store error code shown for each HTTP status (see /support/error-codes/).
STATUS_CODES = {
    400: 'WEB-400', 401: 'WEB-401', 403: 'WEB-403', 404: 'WEB-404', 405: 'WEB-405',
    408: 'WEB-408', 413: 'WEB-413', 429: 'WEB-429', 500: 'WEB-500', 502: 'WEB-502',
    503: 'WEB-503', 504: 'WEB-504',
}

# Statuses with a hand-written headline of their own; everything else uses errors/code.html.
TEMPLATES = {400: '400.html', 403: '403.html', 404: '404.html', 500: '500.html'}

# Bootstrap icon per code, falling back to one per code prefix.
ICONS = {
    'WEB-400': 'exclamation-octagon', 'WEB-401': 'person-lock', 'WEB-403': 'shield-lock',
    'WEB-404': 'signpost-split', 'WEB-405': 'slash-circle', 'WEB-408': 'hourglass-split',
    'WEB-413': 'file-earmark-x', 'WEB-429': 'stopwatch', 'WEB-500': 'cone-striped',
    'WEB-502': 'plug', 'WEB-503': 'tools', 'WEB-504': 'hourglass',
    'NET-001': 'wifi-off', 'NET-002': 'cloud-slash',
}
PREFIX_ICONS = {'PAY': 'credit-card', 'ORD': 'box-seam', 'AI': 'stars', 'TKT': 'life-preserver'}


def icon_for(code):
    return ICONS.get(code) or PREFIX_ICONS.get(code.split('-')[0], 'exclamation-triangle')


def _from_seed(code):
    """The code's wording from the seed list, for when the database can't be read."""
    from support.help_content import ERROR_CODES

    for row in ERROR_CODES:
        if row[0] == code:
            return {'code': row[0], 'title': row[1], 'area': row[2], 'http_status': row[3],
                    'meaning': row[4], 'resolution': row[5], 'ticket_category': row[6]}
    return None


def describe(code):
    """The ErrorCode row for `code` as a dict, from the database or from the seed list if it is down."""
    if not code:
        return None
    try:
        from support.lookup import error_code_data
        from support.models import ErrorCode

        row = ErrorCode.objects.filter(code=code).first()
        if row is not None:
            return error_code_data(row)
    except Exception:  # The database is exactly what fails on a WEB-503.
        logger.warning('Could not read error code %s from the database; using the seed wording.', code)
    return _from_seed(code)


def error_page(request, status, code=None, detail=''):
    """The store's error page for an HTTP status, returned with that status.

    This is what handler400/403/404/500 and the error simulator all call, so a simulated error and a
    real one produce the same response, byte for byte.
    """
    code = code or STATUS_CODES.get(status, '')
    error = describe(code)
    context = {
        'error_code': code, 'error': error, 'http_status': status,
        'icon': icon_for(code), 'detail': detail,
    }
    try:
        return render(request, TEMPLATES.get(status, 'errors/code.html'), context, status=status)
    except Exception:
        # A broken database, a missing template or a bad Host header: still say something useful.
        logger.exception('Could not render the %s error page', status)
        return HttpResponse(plain_page(code, error), status=status, content_type='text/html; charset=utf-8')


def plain_page(code, error=None):
    """A standalone error page: no template, no static files, no database."""
    error = error or _from_seed(code) or {}
    title = error.get('title') or 'Something went wrong'
    meaning = error.get('meaning') or 'The store could not complete your request.'
    resolution = error.get('resolution') or 'Please try again in a minute.'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)} · MJ</title>
<style>body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#f4f4f2;color:#1a1a1a;
display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}}main{{max-width:460px;text-align:center}}
a{{display:inline-block;margin:6px;padding:12px 20px;background:#1a1a1a;color:#fff;text-decoration:none;
font-weight:700;letter-spacing:1px;text-transform:uppercase;font-size:13px}}a.alt{{background:#c9a24a;color:#1a1a1a}}
code{{background:#fff;padding:2px 6px}}</style></head><body><main><h1>{escape(title)}</h1>
<p>Error <code>{escape(code)}</code>: {escape(meaning)}</p><p>{escape(resolution)}</p>
<a href="/">Back to the store</a>
<a class="alt" href="/support/?ask={escape(code)}">Ask the assistant</a>
<a href="/support/error-codes/#{escape(code)}">What this code means</a></main></body></html>"""


class ErrorPageMiddleware:
    """Give Django's body-less error responses the store's error page, for browser navigations.

    Django answers a GET on a POST-only view with an empty 405, and some upload limits produce a
    bare 413. A customer who reaches one of those by following a link should see WEB-405 or
    WEB-413 like any other error, while JSON clients keep the plain response they expect.
    """

    STATUSES = (405, 413)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (response.status_code in self.STATUSES
                and not getattr(response, 'streaming', False)
                and not response.content
                and 'text/html' in request.headers.get('Accept', '')
                and not request.path.startswith('/api/')):
            return error_page(request, response.status_code)
        return response
