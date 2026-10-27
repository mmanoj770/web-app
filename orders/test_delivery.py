import json
import urllib.error
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from . import delivery

INDIA_POST_OK = [{'Status': 'Success', 'PostOffice': [
    {'Name': 'Indiranagar (Bangalore)', 'District': 'Bangalore', 'State': 'Karnataka'}]}]
INDIA_POST_UNKNOWN = [{'Status': 'Error', 'PostOffice': None}]
MONDAY = date(2026, 10, 26)


def respond(payload):
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


class PincodeLookupTests(TestCase):
    def setUp(self):
        cache.clear()

    @mock.patch('urllib.request.urlopen', return_value=respond(INDIA_POST_OK))
    def test_india_post_answer(self, urlopen):
        result = delivery.lookup('560038', today=MONDAY)
        self.assertEqual((result['source'], result['city'], result['state']), ('india_post', 'Bangalore', 'Karnataka'))
        self.assertEqual((result['delivery_days'], result['deliver_by']), (3, '2026-10-29'))
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 3)
        # Cached: a second lookup doesn't call India Post again.
        delivery.lookup('560038')
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch('urllib.request.urlopen', side_effect=TimeoutError('timed out'))
    def test_timeout_falls_back_to_estimate(self, _urlopen):
        with self.assertLogs('orders.delivery', 'WARNING'):
            result = delivery.lookup('400001', today=MONDAY)
        self.assertTrue(result['valid'])
        self.assertEqual((result['source'], result['city'], result['delivery_days']), ('estimate', '', 3))

    @mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('down'))
    def test_non_metro_estimate_skips_sundays(self, _urlopen):
        with self.assertLogs('orders.delivery', 'WARNING'):
            result = delivery.lookup('122001', today=MONDAY)
        self.assertEqual((result['delivery_days'], result['deliver_by']), (6, '2026-11-02'))

    @mock.patch('urllib.request.urlopen', return_value=respond(INDIA_POST_UNKNOWN))
    def test_unknown_pin(self, _urlopen):
        self.assertFalse(delivery.lookup('999999')['valid'])

    def test_invalid_pin_not_sent(self):
        with mock.patch('urllib.request.urlopen') as urlopen:
            self.assertFalse(delivery.lookup('12ab')['valid'])
        urlopen.assert_not_called()

    @mock.patch('urllib.request.urlopen', return_value=respond(INDIA_POST_OK))
    def test_api_endpoint(self, _urlopen):
        response = self.client.get(reverse('api:pincode', args=['560038']))
        self.assertEqual(response.json()['city'], 'Bangalore')
        self.assertEqual(self.client.get(reverse('api:pincode', args=['12'])).status_code, 400)
