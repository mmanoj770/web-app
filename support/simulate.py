"""The error-code demonstration page at /support/error-codes/simulate/.

Every code in the ErrorCode table can be triggered here on purpose, so the store's error handling
can be reviewed end to end without waiting for something to break:

* **Show the page** calls `myproject.errors.error_page()` — the same function handler400 ...
  handler500 call — so the response body, the HTTP status and the JSON log line are the ones a
  customer really gets. Nothing is mocked up or screenshotted.
* **Raise it for real** (WEB-403, WEB-404, WEB-500) raises the actual exception instead, so
  Django's own handler chain runs: `PermissionDenied`, `Http404` and an unhandled exception.
* **Where it happens** links to the place in the store that produces the code by itself, so none
  of it has to be taken on trust.
* The triggers are rate limited, so clicking them quickly shows WEB-429 as well.

Turn the whole page off with `ERROR_SIMULATOR=0` (see myproject/settings.py).
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from myproject.errors import error_page, icon_for

from .models import ErrorCode

logger = logging.getLogger(__name__)

# Triggers allowed per minute per IP address; going over shows WEB-429.
RATE_LIMIT = 30

# Where each code happens in the store on its own: (what to do, a link to that place).
WHERE_IT_HAPPENS = {
    'WEB-400': ('Enter a PIN code that is not six digits at checkout.', '/api/pincode/12a/'),
    'WEB-401': ('Call the ticket API without signing in.', '/api/tickets/'),
    'WEB-403': ('Open the staff dashboard while signed in as a customer.', '/dashboard/'),
    'WEB-404': ('Open any address that does not exist.', '/no-such-page/'),
    'WEB-405': ('Open a form-only endpoint as a link, e.g. add-to-cart.', '/cart/add/1/'),
    'WEB-408': ('Lose the connection halfway through sending a request.', None),
    'WEB-413': ('Attach a photo over 5 MB to a support ticket.', '/support/new/'),
    'WEB-429': (f'Use these buttons more than {RATE_LIMIT} times a minute.', None),
    'WEB-500': ('Any unhandled exception in a view; the page quotes the request ID.', None),
    'WEB-502': ('A deploy or a cold start on Vercel while the request is in flight.', None),
    'WEB-503': ('The database being unreachable. /health/ answers 503 with this code too.', '/health/'),
    'WEB-504': ('A request the server takes longer to answer than the platform waits.', None),
    'AI-429': ('Send more chat messages a minute than ASSISTANT_RATE_LIMIT allows.', None),
    'NET-001': ('Turn Wi-Fi off and reload any page: the service worker serves the offline page.',
                '/offline/'),
    'NET-002': ('Click something that needs the server while the connection drops in and out.', None),
    'PAY-001': ('Pay by card with 4000 0000 0000 0002.', '/orders/checkout/'),
    'PAY-002': ('Pay by card with 4000 0000 0000 9995.', '/orders/checkout/'),
    'PAY-003': ('Pay by card with a number that fails the checksum.', '/orders/checkout/'),
    'PAY-004': ('Pay by UPI with the ID fail@upi.', '/orders/checkout/'),
    'PAY-005': ('Pay by UPI with an ID that is not in name@bank form.', '/orders/checkout/'),
    'ORD-001': ('Put more units in the bag than the product has in stock.', '/cart/'),
    'ORD-002': ('Check out with a product that has been removed from the store.', '/cart/'),
    'ORD-003': ('Open checkout with an empty bag.', '/orders/checkout/'),
    'ORD-004': ('Pay for an order that is already paid or cancelled.', '/orders/'),
}


def _raise_permission_denied(request):
    raise PermissionDenied('Error simulator: a real PermissionDenied, handled by handler403.')


def _raise_not_found(request):
    raise Http404('Error simulator: a real Http404, handled by handler404.')


def _raise_server_error(request):
    logger.info('Error simulator: raising a real exception for WEB-500 (request %s).',
                getattr(request, 'request_id', '-'))
    return 1 / 0  # Unhandled on purpose: Django's handler500 takes it from here.


# Codes that can also be triggered by raising the real exception.
RAISERS = {
    'WEB-403': _raise_permission_denied,
    'WEB-404': _raise_not_found,
    'WEB-500': _raise_server_error,
}

# Codes with no HTTP status of their own: the browser never got an answer at all.
CLIENT_SIDE = {
    'NET-001': '/offline/',
    'NET-002': None,  # Shown by the page itself; the simulator asks the page to prove it.
}


def _rate_limited(request):
    """Allow RATE_LIMIT triggers a minute per IP address, so the demo can't be used to hammer the site."""
    key = f'error-sim:{request.META.get("REMOTE_ADDR", "")}'
    cache.add(key, 0, timeout=60)
    try:
        count = cache.incr(key)
    except ValueError:  # The key expired between add() and incr().
        cache.set(key, 1, timeout=60)
        count = 1
    return count > RATE_LIMIT


def _enabled():
    if not settings.ERROR_SIMULATOR:
        raise Http404('The error simulator is turned off (ERROR_SIMULATOR=0).')


def _groups():
    """Every code in the table, grouped by area in the order the model lists them."""
    rows = {}
    for error in ErrorCode.objects.all():
        where, link = WHERE_IT_HAPPENS.get(error.code, ('', None))
        rows.setdefault(error.area, []).append({
            'error': error, 'where': where, 'link': link, 'icon': icon_for(error.code),
            'can_raise': error.code in RAISERS, 'client_side': error.code in CLIENT_SIDE,
            'trigger': reverse('support:simulate_code', args=[error.code]),
        })
    labels = dict(ErrorCode.Area.choices)
    return [{'key': area, 'label': labels.get(area, area), 'rows': rows[area]}
            for area in labels if area in rows]


def simulator(request):
    """The list of every error code with a button that really triggers it."""
    _enabled()
    groups = _groups()
    return render(request, 'support/simulate.html', {
        'groups': groups,
        'total': sum(len(group['rows']) for group in groups),
        'rate_limit': RATE_LIMIT,
        # ?net=1 asks the page to make a request that really fails, so NET-002 is not faked either.
        'run_net_test': request.GET.get('net') == '1',
    })


def simulate_code(request, code):
    """Trigger one error code and return exactly what the store returns when it happens by itself."""
    _enabled()
    code = code.upper()
    if _rate_limited(request):
        return error_page(request, 429, code='WEB-429',
                          detail=f'The demonstration page allows {RATE_LIMIT} triggers a minute per visitor. '
                                 'This page is the real WEB-429 response, rate limited by the real limiter.')
    error = ErrorCode.objects.filter(code=code).first()
    if error is None:
        raise Http404(f'No error code {code} in the table.')

    if request.GET.get('raise') and code in RAISERS:
        return RAISERS[code](request)

    if code in CLIENT_SIDE:
        # These never reach the server in real life, so hand the demo to the browser.
        target = CLIENT_SIDE[code]
        return redirect(target or f"{reverse('support:simulate')}?net=1")

    detail = ('Triggered from the error-code demonstration page. This is the store\'s real response: '
              f'HTTP {error.http_status}, the same page and the same log line a customer would get.')
    return error_page(request, error.http_status or 500, code=code, detail=detail)
