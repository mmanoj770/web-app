"""Site-wide views: the custom error pages, the offline page and the service worker.

The error handlers are wired up in myproject/urls.py (handler400 ... handler500). They all go
through myproject.errors.error_page(), which reads each code's wording from the ErrorCode table.
"""
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .errors import describe, error_page


def bad_request(request, exception=None):
    """handler400: WEB-400, e.g. a malformed request or an invalid Host header."""
    return error_page(request, 400)


def permission_denied(request, exception=None):
    """handler403: WEB-403, raised by PermissionDenied and the staff-only decorators."""
    return error_page(request, 403)


def page_not_found(request, exception=None):
    """handler404: WEB-404, raised by Http404 and by get_object_or_404()."""
    return error_page(request, 404)


def server_error(request):
    """handler500: WEB-500, for any unhandled exception. Must not assume the database works."""
    return error_page(request, 500)


@require_GET
def offline(request):
    """NET-001: the page the service worker shows when the device has no internet.

    It is served from the service worker's cache with no network at all, so it cannot rely on the
    stylesheet, the Google font or the icon font being cached as well: everything it needs is
    inline in the template.
    """
    return render(request, 'offline.html', {
        'error_code': 'NET-001', 'error': describe('NET-001'), 'offline_codes': [
            describe('NET-001'), describe('NET-002'),
        ],
    })


@never_cache
@require_GET
def service_worker(request):
    """Serve static/js/sw.js from the site root.

    A service worker can only control pages at or below its own URL, so the copy at
    /static/js/sw.js would only cover /static/js/. Serving the same file here, with
    Service-Worker-Allowed, gives it the whole site.
    """
    source = settings.BASE_DIR / 'static' / 'js' / 'sw.js'
    response = HttpResponse(source.read_bytes(), content_type='text/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response
