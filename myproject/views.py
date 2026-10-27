import logging

from django.http import HttpResponseBadRequest, HttpResponseServerError
from django.shortcuts import render

logger = logging.getLogger(__name__)

# Shown if even the styled error page can't be rendered (e.g. the database is down).
PLAIN_500 = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Something went wrong · MJ</title>
<style>body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#f4f4f2;color:#1a1a1a;
display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}main{max-width:460px;text-align:center}
a{display:inline-block;margin:6px;padding:12px 20px;background:#1a1a1a;color:#fff;text-decoration:none;
font-weight:700;letter-spacing:1px;text-transform:uppercase;font-size:13px}a.alt{background:#c9a24a;color:#1a1a1a}
code{background:#fff;padding:2px 6px}</style></head><body><main><h1>Something went wrong</h1>
<p>Error <code>WEB-500</code>: the server hit an unexpected error. It has been logged for our team.
Please try again in a minute.</p><a href="/">Back to the store</a>
<a class="alt" href="/support/?ask=WEB-500">Ask the assistant</a></main></body></html>"""


def server_error(request):
    """Custom 500 page with the site layout and the assistant, or a plain page if that fails too."""
    try:
        return render(request, '500.html', {'error_code': 'WEB-500'}, status=500)
    except Exception:
        logger.exception('Could not render the 500 page')
        return HttpResponseServerError(PLAIN_500)


def bad_request(request, exception=None):
    try:
        return render(request, '400.html', {'error_code': 'WEB-400'}, status=400)
    except Exception:  # e.g. a request with an invalid Host header
        return HttpResponseBadRequest('Bad request (error WEB-400). Please go back and try again.')


def permission_denied(request, exception=None):
    return render(request, '403.html', {'error_code': 'WEB-403'}, status=403)


def page_not_found(request, exception=None):
    return render(request, '404.html', {'error_code': 'WEB-404'}, status=404)
