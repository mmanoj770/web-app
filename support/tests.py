from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from myproject.testing import SHIPPING, make_user
from orders.models import Order

from . import services
from .models import Ticket


class TicketTests(TestCase):
    def setUp(self):
        self.customer = make_user('cust')
        self.busy_agent = make_user('busy', role='agent')
        self.free_agent = make_user('free', role='agent')
        self.order = Order.objects.create(user=self.customer, total=Decimal('100'), **SHIPPING)
        # Give one agent an existing workload.
        services.create_ticket(make_user('other'), Ticket.Category.OTHER, 'Old', 'Old issue')

    def test_ticket_gets_readable_id_and_least_busy_agent(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse('support:create'), {
            'order': self.order.pk, 'category': Ticket.Category.PAYMENT_FAILURE,
            'subject': 'Charged but failed', 'description': 'Money deducted',
        })
        ticket = Ticket.objects.get(subject='Charged but failed')
        self.assertRedirects(response, ticket.get_absolute_url())
        self.assertRegex(ticket.code, r'^TKT-\d{6}$')
        self.assertEqual(ticket.priority, Ticket.Priority.HIGH)
        self.assertEqual(ticket.assigned_to, self.free_agent)

    def test_cannot_attach_someone_elses_order(self):
        other_order = Order.objects.create(user=make_user('x'), total=Decimal('5'), **SHIPPING)
        self.client.force_login(self.customer)
        response = self.client.post(reverse('support:create'), {
            'order': other_order.pk, 'category': Ticket.Category.REFUND, 'subject': 's', 'description': 'd',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('order', response.context['form'].errors)

    def test_customer_cannot_view_other_tickets(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.REFUND, 'Refund', 'Please')
        self.client.force_login(make_user('intruder'))
        self.assertEqual(self.client.get(ticket.get_absolute_url()).status_code, 404)

    def test_customer_reply_reopens_resolved_ticket(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.REFUND, 'Refund', 'Please')
        services.set_status(ticket, Ticket.Status.RESOLVED, by=ticket.assigned_to)
        self.client.force_login(self.customer)
        self.client.post(ticket.get_absolute_url(), {'body': 'Still not refunded'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)
        self.assertIsNone(ticket.resolved_at)

    def test_internal_notes_hidden_from_customer(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.REFUND, 'Refund', 'Please')
        services.add_message(ticket, ticket.assigned_to, 'Secret note', is_internal=True)
        services.add_message(ticket, ticket.assigned_to, 'Public reply')
        self.client.force_login(self.customer)
        response = self.client.get(ticket.get_absolute_url())
        self.assertContains(response, 'Public reply')
        self.assertNotContains(response, 'Secret note')

    def test_customer_can_mark_resolved(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.OTHER, 'Q', 'Q')
        self.client.force_login(self.customer)
        self.client.post(reverse('support:resolve', args=[ticket.code]))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)


class HelpCenterTests(TestCase):
    def setUp(self):
        self.customer = make_user('cust')
        self.agent = make_user('agent', role='agent')
        self.order = Order.objects.create(user=self.customer, total=Decimal('100'), **SHIPPING)
        self.client.force_login(self.customer)

    @staticmethod
    def photo(name='photo.png'):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (10, 10), 'blue').save(buf, 'PNG')
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

    def test_help_center(self):
        response = self.client.get(reverse('support:home'))
        # FAQs are loaded by the page from the API.
        self.assertContains(response, f'data-faq-api="{reverse("api:faqs")}"')
        self.assertContains(response, self.order.number)

    def test_wizard_ticket_with_photos_and_default_subject(self):
        response = self.client.post(reverse('support:create'), {
            'category': 'damaged_product', 'order': self.order.pk, 'subject': '',
            'description': 'Cracked screen', 'attachments': [self.photo(), self.photo('b.png')],
        })
        ticket = Ticket.objects.get()
        self.assertRedirects(response, ticket.get_absolute_url())
        self.assertEqual(ticket.subject, f'Damaged or wrong product · {self.order.number}')
        self.assertEqual(ticket.attachments.count(), 2)

    def test_order_required_for_order_problems(self):
        response = self.client.post(reverse('support:create'), {
            'category': 'missing_delivery', 'order': '', 'description': 'Where is it?',
        })
        self.assertIn('order', response.context['form'].errors)

    def test_too_many_photos_rejected(self):
        response = self.client.post(reverse('support:create'), {
            'category': 'other', 'description': 'x', 'attachments': [self.photo(f'{i}.png') for i in range(6)],
        })
        self.assertIn('attachments', response.context['form'].errors)

    def test_non_image_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(reverse('support:create'), {
            'category': 'other', 'description': 'x',
            'attachments': [SimpleUploadedFile('evil.png', b'not an image', content_type='image/png')],
        })
        self.assertIn('attachments', response.context['form'].errors)

    def test_product_question_is_low_priority(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.PRODUCT_QUESTION, 'Q', 'Does it have NFC?')
        self.assertEqual(ticket.priority, Ticket.Priority.LOW)

    def test_first_response_recorded_on_public_reply_only(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.REFUND, 'Refund', 'Please')
        services.add_message(ticket, self.agent, 'Checking', is_internal=True)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.first_response_at)
        services.add_message(ticket, self.agent, 'Refund approved')
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_response_at)

    def test_overdue_sla(self):
        from datetime import timedelta
        ticket = services.create_ticket(self.customer, Ticket.Category.PAYMENT_FAILURE, 'Paid twice', 'Help')
        Ticket.objects.filter(pk=ticket.pk).update(created_at=ticket.created_at - timedelta(hours=5))
        ticket.refresh_from_db()
        self.assertTrue(ticket.is_overdue)  # High priority: 4 hour first-reply target.

    def test_feedback_only_after_resolution(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.OTHER, 'Q', 'Q')
        url = reverse('support:feedback', args=[ticket.code])
        self.client.post(url, {'csat_rating': 5})
        ticket.refresh_from_db()
        self.assertIsNone(ticket.csat_rating)
        services.set_status(ticket, Ticket.Status.RESOLVED, by=self.agent)
        self.client.post(url, {'csat_rating': 4, 'csat_comment': 'Quick'})
        ticket.refresh_from_db()
        self.assertEqual((ticket.csat_rating, ticket.csat_comment), (4, 'Quick'))

    def test_reply_with_photo(self):
        ticket = services.create_ticket(self.customer, Ticket.Category.OTHER, 'Q', 'Q')
        self.client.post(ticket.get_absolute_url(), {'body': 'Here is a photo', 'attachments': [self.photo()]})
        self.assertEqual(ticket.messages.get().attachments.count(), 1)
