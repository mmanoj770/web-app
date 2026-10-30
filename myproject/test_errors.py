"""Tests for the error pages, the error-code simulator and the offline (NET-001) path."""
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from support import lookup, simulate
from support.models import ErrorCode

from . import errors


class ErrorCodeTableTests(TestCase):
    def test_every_http_status_has_a_code_in_the_table(self):
        """The codes the error pages use all exist in SQL, with the matching HTTP status."""
        for status, code in errors.STATUS_CODES.items():
            with self.subTest(code=code):
                row = ErrorCode.objects.filter(code=code).first()
                self.assertIsNotNone(row, f'{code} is missing from the ErrorCode table')
                self.assertEqual(row.http_status, status)

    def test_assignment_needs_at_least_eight_codes(self):
        self.assertGreaterEqual(ErrorCode.objects.count(), 8)

    def test_seed_wording_matches_the_table(self):
        """errors.describe() falls back to the seed list, so both must agree."""
        for code in ('WEB-404', 'WEB-502', 'NET-001'):
            with self.subTest(code=code):
                self.assertEqual(errors.describe(code)['title'], errors._from_seed(code)['title'])


class ErrorPageTests(TestCase):
    def test_error_page_returns_the_status_and_names_the_code(self):
        for status, code in errors.STATUS_CODES.items():
            with self.subTest(status=status):
                response = self.client.get(f'/support/error-codes/simulate/{code}/')
                self.assertEqual(response.status_code, status)
                self.assertContains(response, code, status_code=status)

    def test_page_text_comes_from_the_database(self):
        """Rewording a code in the admin reaches the error page without a deploy."""
        ErrorCode.objects.filter(code='WEB-502').update(meaning='The upstream gateway misbehaved, uniquely.')
        response = self.client.get('/support/error-codes/simulate/WEB-502/')
        self.assertContains(response, 'uniquely', status_code=502)

    def test_real_404_uses_the_custom_page(self):
        response = self.client.get('/no-such-page-at-all/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'WEB-404', status_code=404)
        self.assertContains(response, "couldn't find that page", status_code=404)

    def test_real_permission_denied_uses_the_custom_page(self):
        response = self.client.get('/support/error-codes/simulate/WEB-403/?raise=1')
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'WEB-403', status_code=403)

    def test_real_unhandled_exception_uses_the_custom_page(self):
        self.client.raise_request_exception = False
        response = self.client.get('/support/error-codes/simulate/WEB-500/?raise=1')
        self.assertEqual(response.status_code, 500)
        self.assertIn(b'WEB-500', response.content)

    def test_plain_page_needs_no_template_or_database(self):
        page = errors.plain_page('WEB-503')
        self.assertIn('WEB-503', page)
        self.assertIn('Service unavailable', page)
        self.assertIn('/support/error-codes/#WEB-503', page)

    def test_plain_page_handles_an_unknown_code(self):
        self.assertIn('Something went wrong', errors.plain_page('ZZZ-999'))


class ErrorPageMiddlewareTests(TestCase):
    """A GET on a POST-only view: a browser gets WEB-405, an API client keeps the bare 405."""

    def test_browser_navigation_gets_the_error_page(self):
        response = self.client.get('/assistant/chat/', headers={'accept': 'text/html'})
        self.assertEqual(response.status_code, 405)
        self.assertContains(response, 'WEB-405', status_code=405)

    def test_json_client_keeps_the_plain_response(self):
        response = self.client.get('/assistant/chat/', headers={'accept': 'application/json'})
        self.assertEqual(response.status_code, 405)
        self.assertNotIn(b'WEB-405', response.content)


class SimulatorTests(TestCase):
    def setUp(self):
        cache.clear()  # The trigger rate limit (WEB-429) lives in the cache.

    def test_the_page_lists_every_code_in_the_table(self):
        response = self.client.get(reverse('support:simulate'))
        self.assertEqual(response.status_code, 200)
        for code in ErrorCode.objects.values_list('code', flat=True):
            self.assertContains(response, code)

    def test_every_code_in_the_table_can_be_triggered(self):
        for error in ErrorCode.objects.all():
            with self.subTest(code=error.code):
                cache.clear()
                response = self.client.get(reverse('support:simulate_code', args=[error.code]))
                if error.code in simulate.CLIENT_SIDE:
                    # These never reach the server in real life, so the browser shows them.
                    self.assertEqual(response.status_code, 302)
                else:
                    self.assertEqual(response.status_code, error.http_status)

    def test_offline_code_sends_you_to_the_offline_page(self):
        response = self.client.get(reverse('support:simulate_code', args=['NET-001']))
        self.assertRedirects(response, reverse('offline'))

    def test_unknown_code_is_a_404(self):
        self.assertEqual(self.client.get('/support/error-codes/simulate/ZZZ-999/').status_code, 404)

    def test_lower_case_codes_work(self):
        self.assertEqual(self.client.get('/support/error-codes/simulate/web-502/').status_code, 502)

    def test_triggering_too_often_gives_web_429(self):
        url = reverse('support:simulate_code', args=['WEB-404'])
        for _ in range(simulate.RATE_LIMIT):
            self.client.get(url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'WEB-429', status_code=429)

    @override_settings(ERROR_SIMULATOR=False)
    def test_can_be_turned_off(self):
        self.assertEqual(self.client.get(reverse('support:simulate')).status_code, 404)
        self.assertEqual(self.client.get('/support/error-codes/simulate/WEB-502/').status_code, 404)

    def test_the_reference_page_links_to_it(self):
        response = self.client.get(reverse('support:error_codes'))
        self.assertContains(response, reverse('support:simulate'))


class OfflineTests(TestCase):
    def test_offline_page_explains_net_001(self):
        response = self.client.get(reverse('offline'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NET-001')
        self.assertContains(response, 'No internet connection')

    def test_offline_page_has_no_stray_template_tags(self):
        """A {# #} comment only works on one line; a multi-line one renders as visible text."""
        body = self.client.get(reverse('offline')).content.decode()
        self.assertNotIn('{#', body)
        self.assertNotIn('{%', body)

    def test_offline_page_is_self_contained(self):
        """It is served from the cache with no network, so it must not need the CSS or the fonts."""
        body = self.client.get(reverse('offline')).content.decode()
        self.assertNotIn('css/store.css', body)
        self.assertNotIn('fonts.googleapis.com', body)
        self.assertNotIn('cdn.jsdelivr.net', body)

    def test_service_worker_is_served_from_the_site_root(self):
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn('javascript', response['Content-Type'])
        self.assertIn(b'/offline/', response.content)

    def test_every_page_registers_the_service_worker(self):
        """app.js is on every page (it is in base.html) and registers the worker at the root scope."""
        self.assertContains(self.client.get('/'), 'js/app.js')
        self.assertContains(self.client.get(reverse('support:error_codes')), 'js/app.js')
        app_js = (settings.BASE_DIR / 'static' / 'js' / 'app.js').read_text()
        self.assertIn("register('/sw.js', { scope: '/' })", app_js)


class AssistantExplainsNewCodesTests(TestCase):
    def test_network_codes_are_recognised(self):
        code, error = lookup.find_error_code('I keep getting NET-001, what now?')
        self.assertEqual(code, 'NET-001')
        self.assertIsNotNone(error)

    def test_bare_http_statuses_map_to_the_new_codes(self):
        for status, expected in ((502, 'WEB-502'), (504, 'WEB-504'), (408, 'WEB-408')):
            with self.subTest(status=status):
                code, error = lookup.find_error_code(f'the site shows error {status}')
                self.assertEqual(code, expected)
                self.assertIsNotNone(error)

    def test_api_reports_the_shared_code_for_a_404(self):
        response = self.client.get('/api/error-codes/ZZZ-999/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['code'], 'WEB-404')
