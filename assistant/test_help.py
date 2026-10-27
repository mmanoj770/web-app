"""The assistant answers FAQs, explains error codes, opens tickets when unsure and stores chats in MongoDB."""
import json
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from myproject.testing import make_user
from support.models import Ticket

from . import fallback, tools
from .models import ChatMessage


@override_settings(LLM_PROVIDER='none')
class AssistantHelpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user('shopper')

    def test_answers_faq_from_database(self):
        result = fallback.reply('How long do refunds take?', self.user)
        self.assertIn('5-7 business days', result['reply'])

    def test_faq_offers_matching_ticket(self):
        result = fallback.reply('my product arrived damaged', self.user)
        self.assertIn('photos', result['reply'])
        self.assertIn('category=damaged_product', result['actions'][0]['url'])

    def test_explains_error_codes(self):
        result = fallback.reply('what does pay-001 mean?', self.user)
        self.assertIn('PAY-001: Card declined', result['reply'])
        self.assertIn('Try another card', result['reply'])
        self.assertIn('category=payment_failure', result['actions'][0]['url'])

    def test_unknown_question_creates_ticket(self):
        result = fallback.reply('do you have a store in Chennai I can visit?', self.user)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.source, Ticket.Source.ASSISTANT)
        self.assertEqual(ticket.customer, self.user)
        self.assertIn(ticket.code, result['reply'])
        self.assertEqual(result['actions'][0]['url'], ticket.get_absolute_url())

        # A follow-up the assistant can't answer goes on the same ticket.
        result = fallback.reply('also can I pick it up from there today?', self.user)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertIn('added this to your open ticket', result['reply'])
        self.assertEqual(ticket.messages.count(), 1)

    def test_unknown_error_code_creates_ticket(self):
        result = fallback.reply('I got error PAY-999 at checkout', self.user)
        self.assertIn("don't have details for error **PAY-999**", result['reply'])
        self.assertEqual(Ticket.objects.count(), 1)

    def test_guest_is_asked_to_log_in_instead(self):
        result = fallback.reply('do you have a store in Chennai I can visit?', AnonymousUser())
        self.assertFalse(Ticket.objects.exists())
        self.assertEqual(result['actions'][0]['label'], 'Log in')

    def test_gibberish_does_not_create_tickets(self):
        for message in ('kjh', 'ghgg bjhg', 'lol'):
            fallback.reply(message, self.user)
        self.assertFalse(Ticket.objects.exists())

    def test_llm_tools(self):
        self.assertEqual(tools.run_tool(self.user, 'explain_error_code', {'code': 'ORD-001'})['title'],
                         'Not enough stock')
        faqs = tools.run_tool(self.user, 'search_faqs', {'query': 'which payment methods'})['faqs']
        self.assertEqual(faqs[0]['question'], 'Which payment methods do you accept?')


@override_settings(LLM_PROVIDER='none', MONGODB_URI='mongodb://example.invalid')
class ChatStorageTests(TestCase):
    def setUp(self):
        cache.clear()

    def _chat(self, message):
        return self.client.post(reverse('assistant:chat'), json.dumps({'message': message}),
                                content_type='application/json')

    @mock.patch('myproject.mongo.insert', return_value=True)
    def test_chats_and_feedback_go_to_mongodb(self, insert):
        data = self._chat('return policy').json()
        collection, document = insert.call_args.args
        self.assertEqual(collection, 'chats')
        self.assertEqual(document['message'], 'return policy')
        self.assertEqual(document['reply'], data['reply'])

        response = self.client.post(reverse('assistant:feedback'), json.dumps({'id': data['id'], 'helpful': False}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        collection, document = insert.call_args.args
        self.assertEqual(collection, 'feedback')
        self.assertEqual((document['type'], document['helpful'], document['question']), ('chat', False, 'return policy'))
        self.assertIs(ChatMessage.objects.get(pk=data['id']).helpful, False)

    def test_feedback_only_for_own_conversation(self):
        data = self._chat('return policy').json()
        self.client.cookies.clear()
        response = self.client.post(reverse('assistant:feedback'), json.dumps({'id': data['id'], 'helpful': True}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 404)

    def test_chat_works_when_mongodb_is_down(self):
        from pymongo.errors import ServerSelectionTimeoutError

        from myproject import mongo

        mongo._state.update(client=None, down_until=0.0)
        with mock.patch('pymongo.collection.Collection.insert_one', side_effect=ServerSelectionTimeoutError('down')), \
                self.assertLogs('myproject.mongo', 'WARNING'):
            response = self._chat('return policy')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChatMessage.objects.count(), 2)  # Still kept in SQL.
        self.assertGreater(mongo._state['down_until'], 0)  # Skips MongoDB for a while.
        mongo._state.update(client=None, down_until=0.0)
