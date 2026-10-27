"""Delivery estimates by PIN code, using the India Post PIN code API.

The API (api.postalpincode.in, free, no key) tells us the city, district and
state for a PIN code. Calls time out after PINCODE_API_TIMEOUT seconds and
results are cached for a day. If the API is slow, down or returns something
unexpected, we fall back to an estimate from the PIN code's first two digits,
so the delivery check and checkout never wait on India Post.
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import date, timedelta

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# First two digits of PIN codes in metro cities (Delhi, Mumbai, Bengaluru, Chennai, Kolkata,
# Hyderabad, Pune, Ahmedabad), which get the faster delivery window.
METRO_PREFIXES = {'11', '40', '56', '60', '70', '50', '41', '38'}
METRO_DISTRICTS = {'new delhi', 'central delhi', 'south delhi', 'mumbai', 'bangalore', 'bengaluru urban',
                   'chennai', 'kolkata', 'hyderabad', 'pune', 'ahmedabad'}
METRO_DAYS, OTHER_DAYS = 3, 6
CACHE_SECONDS = 24 * 60 * 60


def _business_days_from(start, days):
    current, added = start, 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() != 6:  # No deliveries on Sundays.
            added += 1
    return current


def _fetch(pin):
    """Call India Post; returns the first post office dict, False if the PIN doesn't exist, None on failure."""
    url = settings.PINCODE_API_URL.format(pin=pin)
    request = urllib.request.Request(url, headers={'User-Agent': 'MJ-store/1.0', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=settings.PINCODE_API_TIMEOUT) as response:
            data = json.loads(response.read())
        result = data[0]
        if result.get('Status') != 'Success' or not result.get('PostOffice'):
            return False
        return result['PostOffice'][0]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning('India Post PIN lookup for %s failed (%s); using the local estimate.', pin, exc)
        return None


def lookup(pin, today=None):
    """Delivery details for a 6-digit PIN code. `source` says whether India Post answered."""
    pin = str(pin).strip()
    if not (pin.isdigit() and len(pin) == 6) or pin[0] == '0':
        return {'pin': pin, 'valid': False, 'message': 'Enter a valid 6-digit PIN code.', 'source': 'validation'}

    cache_key = f'pincode:{pin}'
    office = cache.get(cache_key)
    if office is None:
        office = _fetch(pin)
        if office is not None:  # Don't cache failures, so the next request retries India Post.
            cache.set(cache_key, office, CACHE_SECONDS)

    result = {'pin': pin, 'valid': True, 'city': '', 'district': '', 'state': '', 'area': ''}
    if office is False:
        return {**result, 'valid': False, 'message': 'We could not find this PIN code.', 'source': 'india_post'}
    if office:
        district = office.get('District') or ''
        result.update(city=district, district=district, state=office.get('State') or '',
                      area=office.get('Name') or '', source='india_post')
        metro = district.lower() in METRO_DISTRICTS or pin[:2] in METRO_PREFIXES
    else:
        result['source'] = 'estimate'
        metro = pin[:2] in METRO_PREFIXES

    days = METRO_DAYS if metro else OTHER_DAYS
    deliver_by = _business_days_from(today or date.today(), days)
    result.update(delivery_days=days, deliver_by=deliver_by.isoformat(),
                  deliver_by_label=deliver_by.strftime('%a, %d %b'))
    place = ', '.join(part for part in (result['area'], result['state']) if part)
    result['message'] = f'Free delivery{f" to {place}" if place else ""} by {result["deliver_by_label"]}'
    return result
