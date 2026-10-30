import json
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import anthropic
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from myproject.testing import SHIPPING, make_product, make_user
from orders.models import Order
from support.models import Ticket

from . import fallback, openai_compat, providers, services
from .llm import LLMUnavailable
from .models import ChatMessage

CHAT_URL = reverse('assistant:chat')


def text(t):
    return SimpleNamespace(type='text', text=t)


def tool_use(id_, name, input_):
    return SimpleNamespace(type='tool_use', id=id_, name=name, input=input_)


class FakeClient:
    """Stands in for anthropic.Anthropic, replaying scripted responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        # Snapshot the messages: the caller keeps appending to the same list.
        self.requests.append(dict(kwargs, messages=list(kwargs['messages'])))
        return self.responses.pop(0)


def response(stop_reason, *content):
    return SimpleNamespace(stop_reason=stop_reason, content=list(content))


def post(client, message):
    return client.post(CHAT_URL, json.dumps({'message': message}), content_type='application/json')


@override_settings(LLM_PROVIDER='none')
class FallbackAssistantTests(TestCase):
    def setUp(self):
        cache.clear()  # Reset the per-IP rate limit.
        self.budget = make_product('Lenovo IdeaPad', price='52990')
        self.pricey = make_product('MacBook Air', price='114900', brand='Apple')
        make_product('Sony Headphones', price='29990', category='Headphones')
        make_product('Pixel Phone', price='39999', category='Smartphones', brand='Google')

    def test_recommends_within_budget(self):
        data = post(self.client, 'I need a laptop under 60000').json()
        self.assertEqual([p['name'] for p in data['products']], ['Lenovo IdeaPad'])
        self.assertIn('within ₹60,000', data['reply'])
        self.assertIn('**Lenovo IdeaPad**', data['reply'])
        self.assertEqual(data['assistant'], services.OFFLINE_LABEL)

    def test_phone_does_not_match_headphones(self):
        data = post(self.client, 'best phone under 50000').json()
        self.assertEqual([p['name'] for p in data['products']], ['Pixel Phone'])

    def test_budget_with_k_suffix(self):
        self.assertEqual(fallback._budget('headphones under 30k'), 30000)

    def test_order_status_requires_login(self):
        data = post(self.client, 'Where is my order?').json()
        self.assertIn('log in', data['reply'])

    def test_order_status_for_logged_in_customer(self):
        user = make_user('cust')
        order = Order.objects.create(user=user, total=Decimal('10'), status=Order.Status.SHIPPED,
                                     carrier='Delhivery', tracking_number='DL42', **SHIPPING)
        self.client.force_login(user)
        data = post(self.client, 'where is my order').json()
        self.assertIn(order.number, data['reply'])
        self.assertIn('DL42', data['reply'])

    def test_damaged_product_offers_ticket(self):
        data = post(self.client, 'My headphones arrived damaged').json()
        self.assertEqual(data['actions'][0]['url'], reverse('support:create') + '?category=damaged_product')

    def test_conversation_is_saved_and_cleared(self):
        post(self.client, 'hello')
        history = self.client.get(reverse('assistant:history')).json()
        self.assertEqual([m['role'] for m in history['messages']], ['user', 'assistant'])
        self.client.post(reverse('assistant:clear'))
        self.assertFalse(ChatMessage.objects.exists())

    def test_vague_problem_with_typo_asks_follow_up(self):
        data = post(self.client, 'i have a probelm').json()
        self.assertIn("What's the problem about?", data['reply'])
        self.assertIn("My order hasn't arrived", data['suggestions'])
        self.assertEqual(data['products'], [])

    def test_follow_up_answer_offers_ticket(self):
        data = post(self.client, "My order hasn't arrived").json()
        self.assertEqual(data['actions'][0]['url'], reverse('support:create') + '?category=missing_delivery')

    def test_typos_in_product_search(self):
        self.assertEqual(fallback.correct_spelling('lenovo lapotp'), 'lenovo laptop')
        data = post(self.client, 'lapotp under 60k').json()
        self.assertEqual([p['name'] for p in data['products']], ['Lenovo IdeaPad'])

    def test_gibberish_gets_options_not_products(self):
        data = post(self.client, 'asdfgh').json()
        self.assertEqual(data['products'], [])
        self.assertTrue(data['suggestions'])

    def test_small_talk(self):
        self.assertIn('welcome', post(self.client, 'thank you').json()['reply'])

    def test_empty_message_rejected(self):
        self.assertEqual(post(self.client, '   ').status_code, 400)

    @override_settings(ASSISTANT_RATE_LIMIT=2)
    def test_rate_limit(self):
        self.assertEqual(post(self.client, 'hi').status_code, 200)
        self.assertEqual(post(self.client, 'hi').status_code, 200)
        self.assertEqual(post(self.client, 'hi').status_code, 429)


@override_settings(LLM_PROVIDER='anthropic', LLM_MODEL='', LLM_API_KEY='')
@mock.patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
class ClaudeAssistantTests(TestCase):
    def setUp(self):
        cache.clear()
        self.laptop = make_product('Lenovo IdeaPad Slim (Ryzen 5)', price='52990', brand='Lenovo')
        self.user = make_user('cust', role='customer')
        make_user('agent', role='agent')

    def test_tool_loop_searches_and_shows_mentioned_products(self):
        fake = FakeClient([
            response('tool_use', tool_use('t1', 'search_products', {'query': 'laptop', 'max_price': 60000})),
            # The reply uses a shortened name; the card should still be shown.
            response('end_turn', text('I recommend the IdeaPad Slim at ₹52,990.')),
        ])
        with mock.patch('assistant.llm.anthropic.Anthropic', return_value=fake):
            data = post(self.client, 'laptop under 60000').json()

        self.assertEqual(data['reply'], 'I recommend the IdeaPad Slim at ₹52,990.')
        self.assertEqual([p['name'] for p in data['products']], ['Lenovo IdeaPad Slim (Ryzen 5)'])
        self.assertTrue(data['assistant'].startswith('Claude'))

        first, second = fake.requests
        self.assertEqual(first['model'], 'claude-opus-5-5')
        self.assertEqual(first['fallbacks'], 'default')
        self.assertEqual(first['messages'], [{'role': 'user', 'content': 'laptop under 60000'}])
        tool_result = second['messages'][-1]['content'][0]
        self.assertEqual(tool_result['tool_use_id'], 't1')
        self.assertIn('Lenovo IdeaPad', tool_result['content'])

    def test_creates_ticket_for_logged_in_customer(self):
        self.client.force_login(self.user)
        fake = FakeClient([
            response('tool_use', tool_use('t1', 'create_support_ticket', {
                'category': 'refund', 'subject': 'Refund for headphones', 'description': 'Wants a refund',
            })),
            response('end_turn', text('Done! Your ticket is open.')),
        ])
        with mock.patch('assistant.llm.anthropic.Anthropic', return_value=fake):
            data = post(self.client, 'yes please raise a refund ticket').json()

        ticket = Ticket.objects.get()
        self.assertEqual(ticket.source, Ticket.Source.ASSISTANT)
        self.assertEqual(ticket.customer, self.user)
        self.assertEqual(data['actions'][0]['url'], ticket.get_absolute_url())

    def test_guest_cannot_use_order_tools(self):
        fake = FakeClient([
            response('tool_use', tool_use('t1', 'get_my_orders', {})),
            response('end_turn', text('Please log in first.')),
        ])
        with mock.patch('assistant.llm.anthropic.Anthropic', return_value=fake):
            post(self.client, 'show my orders')
        tool_result = fake.requests[1]['messages'][-1]['content'][0]
        self.assertTrue(tool_result['is_error'])

    def test_history_is_sent_on_later_turns(self):
        fake = FakeClient([response('end_turn', text('Hi!')), response('end_turn', text('Sure.'))])
        with mock.patch('assistant.llm.anthropic.Anthropic', return_value=fake):
            post(self.client, 'hello')
            post(self.client, 'show me laptops')
        self.assertEqual(
            fake.requests[1]['messages'],
            [{'role': 'user', 'content': 'hello'}, {'role': 'assistant', 'content': 'Hi!'},
             {'role': 'user', 'content': 'show me laptops'}],
        )

    def test_refusal_returns_safe_message(self):
        fake = FakeClient([response('refusal')])
        with mock.patch('assistant.llm.anthropic.Anthropic', return_value=fake):
            data = post(self.client, 'something odd').json()
        self.assertIn("can't help", data['reply'])

    def test_falls_back_to_rules_when_api_unavailable(self):
        with mock.patch('assistant.llm.anthropic.Anthropic', side_effect=anthropic.AnthropicError('boom')):
            data = post(self.client, 'laptop under 60000').json()
        self.assertEqual([p['name'] for p in data['products']], ['Lenovo IdeaPad Slim (Ryzen 5)'])
        self.assertEqual(data['assistant'], services.OFFLINE_LABEL)

    def test_uses_rules_without_credentials(self):
        with mock.patch.dict('os.environ', {'ANTHROPIC_API_KEY': '', 'XDG_CONFIG_HOME': '/nonexistent'}), \
                mock.patch('assistant.llm.anthropic.Anthropic') as client_cls:
            data = post(self.client, 'laptop under 60000').json()
        client_cls.assert_not_called()
        self.assertEqual([p['name'] for p in data['products']], ['Lenovo IdeaPad Slim (Ryzen 5)'])


class FakeOpenAI:
    """Replays OpenAI-style chat completion responses."""

    def __init__(self, messages):
        self.messages = list(messages)
        self.bodies = []

    def __call__(self, config, body):
        self.bodies.append(json.loads(json.dumps(body)))
        return {'choices': [{'message': self.messages.pop(0)}]}


@override_settings(LLM_PROVIDER='ollama', LLM_MODEL='', LLM_API_KEY='', LLM_BASE_URL='', LLM_MODE='tools')
class OpenAICompatibleAssistantTests(TestCase):
    def setUp(self):
        cache.clear()
        self.watch = make_product('Galaxy Watch6', price='18999', category='Smartwatches', brand='Samsung')

    def test_tool_loop(self):
        fake = FakeOpenAI([
            {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'call_1', 'type': 'function',
                 'function': {'name': 'search_products', 'arguments': '{"category": "smartwatches"}'}}]},
            {'role': 'assistant', 'content': 'The Galaxy Watch6 is a great pick.'},
        ])
        with mock.patch.object(openai_compat, 'post', fake):
            data = post(self.client, 'recommend a smartwatch').json()
        self.assertEqual(data['reply'], 'The Galaxy Watch6 is a great pick.')
        self.assertEqual([p['name'] for p in data['products']], ['Galaxy Watch6'])
        self.assertEqual(data['assistant'], 'Ollama · llama3.2')

        first, second = fake.bodies
        self.assertEqual(first['model'], 'llama3.2')
        self.assertEqual(first['messages'][0]['role'], 'system')
        self.assertEqual(first['tools'][0]['function']['name'], 'search_products')
        tool_message = second['messages'][-1]
        self.assertEqual(tool_message['role'], 'tool')
        self.assertEqual(tool_message['tool_call_id'], 'call_1')
        self.assertIn('Galaxy Watch6', tool_message['content'])

    def test_bad_tool_arguments_are_reported_to_the_model(self):
        fake = FakeOpenAI([
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': 'c1', 'type': 'function', 'function': {'name': 'search_products', 'arguments': '{oops'}}]},
            {'role': 'assistant', 'content': 'Sorry, let me try again.'},
        ])
        with mock.patch.object(openai_compat, 'post', fake):
            post(self.client, 'watch')
        self.assertIn('error', json.loads(fake.bodies[1]['messages'][-1]['content']))

    def test_unreachable_server_falls_back_to_rules(self):
        with mock.patch.object(openai_compat, 'post', side_effect=LLMUnavailable('connection refused')):
            data = post(self.client, 'smartwatch').json()
        self.assertEqual([p['name'] for p in data['products']], ['Galaxy Watch6'])
        self.assertEqual(data['assistant'], services.OFFLINE_LABEL)


class ProviderSelectionTests(SimpleTestCase):
    NO_KEYS = {'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': '', 'GEMINI_API_KEY': '', 'GROQ_API_KEY': '',
               'OPENROUTER_API_KEY': '', 'XDG_CONFIG_HOME': '/nonexistent'}

    def resolve(self, env=None, ollama=(), **settings):
        defaults = {'LLM_PROVIDER': 'auto', 'LLM_MODEL': '', 'LLM_API_KEY': '', 'LLM_BASE_URL': ''}
        defaults.update(settings)
        with override_settings(**defaults), mock.patch.dict('os.environ', {**self.NO_KEYS, **(env or {})}), \
                mock.patch('assistant.providers.ollama_models', return_value=list(ollama)):
            return providers.resolve()

    def test_auto_detects_running_ollama(self):
        config = self.resolve(ollama=['llama3.2:latest', 'mj-assistant:latest'])
        self.assertEqual((config.name, config.model), ('ollama', 'mj-assistant'))

    def test_cloud_key_beats_local_ollama(self):
        self.assertEqual(self.resolve({'GROQ_API_KEY': 'g'}, ollama=['qwen2.5:3b']).name, 'groq')

    def test_no_keys_means_rule_based(self):
        self.assertIsNone(self.resolve())

    def test_auto_prefers_anthropic(self):
        config = self.resolve({'ANTHROPIC_API_KEY': 'a', 'OPENAI_API_KEY': 'o'})
        self.assertEqual((config.name, config.model), ('anthropic', 'claude-opus-5-5'))

    def test_auto_uses_openai_compatible_key(self):
        config = self.resolve({'GROQ_API_KEY': 'g'})
        self.assertEqual(config.name, 'groq')
        self.assertEqual(config.api_key, 'g')
        self.assertIn('groq.com', config.base_url)

    def test_auto_skips_a_paused_provider(self):
        """A key the provider rejects must not be retried on every message."""
        cache.clear()
        self.addCleanup(cache.clear)
        providers.pause('groq', 'groq returned HTTP 401: invalid api key')
        # It falls through to the next provider that has a key...
        self.assertEqual(self.resolve({'GROQ_API_KEY': 'g', 'OPENROUTER_API_KEY': 'o'}).name, 'openrouter')
        # ...and to the rule-based assistant when it was the only one.
        self.assertIsNone(self.resolve({'GROQ_API_KEY': 'g'}))

    def test_auto_skips_paused_anthropic(self):
        cache.clear()
        self.addCleanup(cache.clear)
        providers.pause('anthropic', 'anthropic returned HTTP 400: credit balance too low')
        self.assertEqual(self.resolve({'ANTHROPIC_API_KEY': 'a', 'GROQ_API_KEY': 'g'}).name, 'groq')

    def test_an_explicitly_named_provider_is_used_even_when_paused(self):
        """LLM_PROVIDER=groq means groq: the pause only steers "auto"."""
        cache.clear()
        self.addCleanup(cache.clear)
        providers.pause('groq', 'groq returned HTTP 401')
        self.assertEqual(self.resolve({'GROQ_API_KEY': 'g'}, LLM_PROVIDER='groq').name, 'groq')

    def test_explicit_provider_and_model(self):
        config = self.resolve({'GEMINI_API_KEY': 'k'}, LLM_PROVIDER='gemini', LLM_MODEL='gemini-x')
        self.assertEqual((config.name, config.model), ('gemini', 'gemini-x'))

    def test_ollama_needs_no_key_and_accepts_custom_url(self):
        config = self.resolve(LLM_PROVIDER='ollama', LLM_BASE_URL='http://gpu-box:11434/v1')
        self.assertEqual(config.base_url, 'http://gpu-box:11434/v1')

    def test_missing_key_for_explicit_provider(self):
        self.assertIsNone(self.resolve(LLM_PROVIDER='openai'))

    def test_unknown_provider(self):
        self.assertIsNone(self.resolve(LLM_PROVIDER='skynet'))

    def test_none_disables_llm(self):
        self.assertIsNone(self.resolve({'ANTHROPIC_API_KEY': 'a'}, LLM_PROVIDER='none'))

    def test_name_variants(self):
        variants = services._name_variants('Samsung Galaxy S24 Ultra (12 GB / 256 GB)', 'Samsung')
        self.assertIn('galaxy s24 ultra', variants)
        self.assertIn('samsung galaxy s24 ultra', variants)


@override_settings(LLM_PROVIDER='ollama', LLM_MODEL='', LLM_API_KEY='', LLM_BASE_URL='', LLM_MODE='auto')
class GroundedAssistantTests(TestCase):
    """Small local models only phrase facts the backend gathers."""

    def setUp(self):
        cache.clear()
        self.laptop = make_product('Lenovo IdeaPad Slim', price='52990', brand='Lenovo')
        make_product('MacBook Air', price='114900', brand='Apple')

    def reply_with(self, text):
        return mock.patch.object(openai_compat, 'post', FakeOpenAI([{'role': 'assistant', 'content': text}]))

    def test_reply_is_written_from_facts(self):
        fake = FakeOpenAI([{'role': 'assistant', 'content': 'The IdeaPad Slim at ₹52,990 fits your ₹60,000 budget.'}])
        with mock.patch.object(openai_compat, 'post', fake):
            data = post(self.client, 'laptop under 60000').json()
        self.assertIn('IdeaPad Slim', data['reply'])
        self.assertEqual([p['name'] for p in data['products']], ['Lenovo IdeaPad Slim'])
        prompt = fake.bodies[0]['messages'][-1]['content']
        self.assertIn('FACTS', prompt)
        self.assertIn('₹52,990', prompt)
        self.assertNotIn('tools', fake.bodies[0])

    def test_invented_price_falls_back_to_rules(self):
        with self.reply_with('Try the Jabra Elite 85t at ₹13,990!'):
            data = post(self.client, 'laptop under 60000').json()
        self.assertNotIn('Jabra', data['reply'])
        self.assertIn('**Lenovo IdeaPad Slim**', data['reply'])

    def test_links_and_placeholders_removed(self):
        with self.reply_with('Raise a ticket by clicking here: [Support Ticket URL]. See [details](/x/).'):
            data = post(self.client, 'i have a problem').json()
        self.assertNotIn('[', data['reply'])
        self.assertIn('button below', data['reply'])
        self.assertTrue(data['suggestions'])  # Follow-up chips still come from the backend.

    def test_cloud_models_use_tools(self):
        self.assertTrue(services.uses_grounded_mode(providers.ProviderConfig('ollama', 'm')))
        self.assertFalse(services.uses_grounded_mode(providers.ProviderConfig('openai', 'm')))
