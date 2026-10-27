"""Vercel AI Gateway provider: OIDC authentication on Vercel and pausing after credential errors."""
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from . import providers
from .llm import LLMUnavailable

GATEWAY_REPLY = {'choices': [{'message': {'content': 'Refunds take 5-7 business days.'}}]}


@override_settings(LLM_PROVIDER='auto', LLM_MODEL='', ON_VERCEL=True)
@mock.patch.dict('os.environ', {}, clear=False)
@mock.patch('assistant.providers.anthropic_has_credentials', return_value=False)
@mock.patch('assistant.providers.ollama_models', return_value=[])
class GatewayProviderTests(TestCase):
    def setUp(self):
        cache.clear()
        for name in ('AI_GATEWAY_API_KEY', 'VERCEL_OIDC_TOKEN', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GROQ_API_KEY',
                     'OPENROUTER_API_KEY'):
            patcher = mock.patch.dict('os.environ', {name: ''})
            patcher.start()
            self.addCleanup(patcher.stop)

    def _chat(self, message='How long do refunds take?', **headers):
        return self.client.post(reverse('assistant:chat'), json.dumps({'message': message}),
                                content_type='application/json', **headers)

    def test_no_token_means_rule_based(self, *_):
        self.assertIsNone(providers.resolve())

    def test_uses_request_oidc_token_on_vercel(self, *_):
        with mock.patch('assistant.openai_compat.post', return_value=GATEWAY_REPLY) as post:
            data = self._chat(HTTP_X_VERCEL_OIDC_TOKEN='oidc-123').json()
        config, body = post.call_args.args
        self.assertEqual((config.name, config.api_key, config.base_url),
                         ('gateway', 'oidc-123', 'https://ai-gateway.vercel.sh/v1'))
        self.assertEqual(body['model'], 'anthropic/claude-haiku-5.5')
        self.assertEqual(data['assistant'], 'Vercel AI Gateway · anthropic/claude-haiku-5.5')
        self.assertEqual(data['reply'], 'Refunds take 5-7 business days.')

    def test_billing_error_pauses_gateway_and_falls_back(self, *_):
        error = LLMUnavailable('gateway returned HTTP 403: AI Gateway requires a valid credit card on file')
        with mock.patch('assistant.openai_compat.post', side_effect=error) as post, \
                self.assertLogs('assistant', 'WARNING'):
            first = self._chat(HTTP_X_VERCEL_OIDC_TOKEN='oidc-123').json()
            second = self._chat(HTTP_X_VERCEL_OIDC_TOKEN='oidc-123').json()
        self.assertEqual(post.call_count, 1)  # The second message skipped the paused gateway.
        self.assertIn('5-7 business days', first['reply'])  # Rule-based answer from the FAQs.
        self.assertEqual(second['assistant'], 'Smart assistant')
        health = self.client.get(reverse('health')).json()
        self.assertIn('credit card', health['checks']['assistant']['paused']['gateway'])

    @override_settings(ON_VERCEL=False)
    def test_header_ignored_off_vercel(self, *_):
        with mock.patch('assistant.openai_compat.post') as post:
            self._chat(HTTP_X_VERCEL_OIDC_TOKEN='spoofed')
        post.assert_not_called()
