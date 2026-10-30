import json
from unittest import mock

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from . import views


class HealthAndLoggingTests(TestCase):
    def test_health_ok(self):
        response = self.client.get(reverse('health'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['checks']['database']['ok'])
        self.assertIsNone(data['checks']['mongodb']['ok'])  # Not configured in tests.
        self.assertIn('no-cache', response['Cache-Control'])

    def test_health_503_when_database_is_down(self):
        with mock.patch('myproject.observability.connection.cursor', side_effect=Exception('db down')):
            response = self.client.get(reverse('health'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['status'], 'down')

    def test_requests_are_logged_with_an_id(self):
        with self.assertLogs('mj.requests', 'INFO') as logs:
            response = self.client.get(reverse('support:home'), HTTP_X_REQUEST_ID='abc123')
        self.assertEqual(response['X-Request-ID'], 'abc123')
        self.assertIn('app;dur=', response['Server-Timing'])
        entry = json.loads(logs.records[-1].getMessage())
        self.assertEqual((entry['method'], entry['path'], entry['status']), ('GET', '/support/', 200))
        self.assertEqual(entry['request_id'], 'abc123')

    def test_errors_logged_as_warnings(self):
        with self.assertLogs('mj.requests', 'WARNING') as logs:
            self.client.get('/no-such-page/')
        self.assertEqual(json.loads(logs.records[-1].getMessage())['status'], 404)


class ErrorPageTests(TestCase):
    def test_404_page(self):
        response = self.client.get('/no-such-page/')
        self.assertContains(response, 'WEB-404', status_code=404)
        self.assertContains(response, 'data-ask=', status_code=404)
        self.assertContains(response, 'id="ai-panel"', status_code=404)

    def test_500_page(self):
        request = RequestFactory().get('/')
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()
        request.session = {}
        response = views.server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, 'WEB-500', status_code=500)
        self.assertContains(response, 'Ask the assistant', status_code=500)

    def test_500_falls_back_to_plain_page(self):
        # The pages are rendered by myproject.errors now; myproject.views only wires up the handlers.
        with mock.patch('myproject.errors.render', side_effect=Exception('template broke')), \
                self.assertLogs('myproject.errors', 'ERROR'):
            response = views.server_error(RequestFactory().get('/'))
        self.assertContains(response, 'WEB-500', status_code=500)
        self.assertContains(response, '/support/?ask=WEB-500', status_code=500)

    @override_settings(DEBUG=False)
    def test_unhandled_exception_uses_custom_500(self):
        self.client.raise_request_exception = False
        with mock.patch('catalog.views.render', side_effect=RuntimeError('boom')), \
                mock.patch('myproject.observability.logger'):
            response = self.client.get(reverse('catalog:home'))
        self.assertContains(response, 'WEB-500', status_code=500)
        self.assertContains(response, 'Ask the assistant', status_code=500)
