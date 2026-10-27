import json

from django.test import TestCase
from django.urls import reverse

from myproject.testing import make_user

from . import services
from .models import FAQ, ErrorCode, Ticket


class HelpContentTests(TestCase):
    def test_seeded_by_migration(self):
        self.assertGreaterEqual(FAQ.objects.filter(is_published=True).count(), 10)
        self.assertGreaterEqual(ErrorCode.objects.count(), 8)

    def test_faq_api_lists_and_searches(self):
        data = self.client.get(reverse('api:faqs')).json()
        self.assertEqual(data['count'], FAQ.objects.filter(is_published=True).count())
        self.assertIn({'key': 'payments', 'label': 'Payments & refunds'}, data['categories'])

        data = self.client.get(reverse('api:faqs'), {'q': 'how long do refunds take'}).json()
        self.assertEqual(data['results'][0]['question'], 'How long do refunds take?')

        data = self.client.get(reverse('api:faqs'), {'category': 'returns'}).json()
        self.assertTrue(data['results'])
        self.assertTrue(all(f['category'] == 'returns' for f in data['results']))

    def test_unpublished_faq_hidden(self):
        faq = FAQ.objects.get(question='How long do refunds take?')
        faq.is_published = False
        faq.save()
        questions = [f['question'] for f in self.client.get(reverse('api:faqs')).json()['results']]
        self.assertNotIn(faq.question, questions)
        self.assertEqual(self.client.get(reverse('api:faq', args=[faq.pk])).status_code, 404)

    def test_error_code_api(self):
        data = self.client.get(reverse('api:error_codes')).json()
        self.assertGreaterEqual(data['count'], 8)
        detail = self.client.get(reverse('api:error_code', args=['pay-001'])).json()
        self.assertEqual(detail['code'], 'PAY-001')
        self.assertEqual(detail['title'], 'Card declined')
        response = self.client.get(reverse('api:error_code', args=['XYZ-999']))
        self.assertEqual(response.status_code, 404)

    def test_required_http_error_codes(self):
        statuses = set(ErrorCode.objects.values_list('http_status', flat=True))
        self.assertTrue({400, 401, 403, 404, 429, 500, 503} <= statuses)
        self.assertTrue(ErrorCode.objects.filter(code__startswith='PAY-').exists())  # Site-specific codes.

    def test_api_errors_carry_codes(self):
        self.assertEqual(self.client.get(reverse('api:tickets')).json()['code'], 'WEB-401')

    def test_pages_load_from_api(self):
        self.assertContains(self.client.get(reverse('support:faq')), reverse('api:faqs'))
        self.assertContains(self.client.get(reverse('support:home')), reverse('api:faqs'))
        self.assertContains(self.client.get(reverse('support:error_codes')), reverse('api:error_codes'))


class TicketApiTests(TestCase):
    def setUp(self):
        self.customer = make_user('cust')
        self.agent = make_user('agent', role='agent')
        self.client.force_login(self.customer)

    def _create(self, **data):
        body = {'category': 'other', 'subject': 'Gift wrap?', 'description': 'Can you gift wrap my order?', **data}
        return self.client.post(reverse('api:tickets'), json.dumps(body), content_type='application/json')

    def _patch(self, code, data):
        return self.client.patch(reverse('api:ticket', args=[code]), json.dumps(data), content_type='application/json')

    def test_crud(self):
        response = self._create()
        self.assertEqual(response.status_code, 201)
        code = response.json()['ticket_id']

        listed = self.client.get(reverse('api:tickets')).json()['results']
        self.assertEqual([t['ticket_id'] for t in listed], [code])
        self.assertEqual(self.client.get(reverse('api:ticket', args=[code])).json()['subject'], 'Gift wrap?')

        response = self._patch(code, {'subject': 'Gift wrapping', 'message': 'For a birthday'})
        self.assertEqual(response.json()['subject'], 'Gift wrapping')
        self.assertEqual(response.json()['messages'][-1]['body'], 'For a birthday')

        response = self.client.delete(reverse('api:ticket', args=[code]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Ticket.objects.filter(code=code).exists())

    def test_validation(self):
        self.assertEqual(self._create(category='nope').status_code, 400)
        self.assertEqual(self._create(subject='').status_code, 400)
        self.assertEqual(self._create(order_number='ORD-999999').status_code, 400)

    def test_customer_can_resolve_but_not_set_other_statuses(self):
        code = self._create().json()['ticket_id']
        self.assertEqual(self._patch(code, {'status': 'closed'}).status_code, 400)
        self.assertEqual(self._patch(code, {'status': 'resolved'}).json()['status'], 'resolved')

    def test_cannot_delete_after_agent_replied(self):
        code = self._create().json()['ticket_id']
        services.add_message(Ticket.objects.get(code=code), self.agent, 'Sure, we can do that.')
        self.assertEqual(self.client.delete(reverse('api:ticket', args=[code])).status_code, 403)

    def test_other_customers_tickets_are_hidden(self):
        theirs = services.create_ticket(make_user('other'), 'other', 'Theirs', 'Private')
        self.assertEqual(self.client.get(reverse('api:ticket', args=[theirs.code])).status_code, 404)
        self.assertEqual(self.client.delete(reverse('api:ticket', args=[theirs.code])).status_code, 404)

    def test_agent_sees_all_and_sets_status(self):
        code = self._create().json()['ticket_id']
        self.client.force_login(self.agent)
        self.assertEqual(len(self.client.get(reverse('api:tickets')).json()['results']), 1)
        self.assertEqual(self._patch(code, {'status': 'in_progress'}).json()['status'], 'in_progress')

    def test_guests_get_401(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('api:tickets')).status_code, 401)
