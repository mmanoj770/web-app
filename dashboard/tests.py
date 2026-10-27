from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from myproject.testing import SHIPPING, make_product, make_user
from orders.models import Order
from support import services
from support.models import Ticket


class DashboardAccessTests(TestCase):
    def setUp(self):
        self.customer = make_user('cust')
        self.agent = make_user('agent', role='agent')
        self.admin = make_user('boss', role='admin')

    def test_customers_are_forbidden(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse('dashboard:home')).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse('dashboard:home'))
        self.assertEqual(response.status_code, 302)

    def test_agent_sees_tickets_but_not_admin_pages(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse('dashboard:home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard:tickets')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard:products')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboard:users')).status_code, 403)

    def test_admin_pages(self):
        make_product()
        self.client.force_login(self.admin)
        for name in ('home', 'tickets', 'orders', 'products', 'users'):
            self.assertEqual(self.client.get(reverse(f'dashboard:{name}')).status_code, 200, name)


class TicketHandlingTests(TestCase):
    def setUp(self):
        self.customer = make_user('cust')
        self.agent = make_user('agent', role='agent')
        self.ticket = services.create_ticket(self.customer, Ticket.Category.DAMAGED_PRODUCT, 'Broken', 'Cracked')
        self.url = reverse('dashboard:ticket_detail', args=[self.ticket.code])

    def test_agent_reply_moves_ticket_in_progress(self):
        self.client.force_login(self.agent)
        self.client.post(self.url, {'action': 'reply', 'body': 'Sorry, sending a replacement'})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)

    def test_agent_resolves_ticket(self):
        self.client.force_login(self.agent)
        self.client.post(self.url, {'action': 'update', 'status': Ticket.Status.RESOLVED, 'priority': 'high'})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.RESOLVED)
        self.assertTrue(self.ticket.messages.filter(is_system=True).exists())

    def test_other_agent_cannot_reply(self):
        self.client.force_login(make_user('agent2', role='agent'))
        self.client.post(self.url, {'action': 'reply', 'body': 'Hijack'})
        self.assertFalse(self.ticket.messages.filter(body='Hijack').exists())

    def test_agent_can_take_unassigned_ticket(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(assigned_to=None)
        other = make_user('agent2', role='agent')
        self.client.force_login(other)
        self.client.post(self.url, {'action': 'take'})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, other)


class OrderManagementTests(TestCase):
    def setUp(self):
        self.admin = make_user('boss', role='admin')
        self.order = Order.objects.create(user=make_user('cust'), total=Decimal('10'), status=Order.Status.PAID,
                                          **SHIPPING)
        self.url = reverse('dashboard:order_detail', args=[self.order.pk])

    def test_shipping_requires_tracking_number(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'status': Order.Status.SHIPPED})
        self.assertIn('tracking_number', response.context['form'].errors)

    def test_ship_order(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {'status': Order.Status.SHIPPED, 'carrier': 'BlueDart', 'tracking_number': 'BD123'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(self.order.tracking_number, 'BD123')
        self.assertEqual(self.order.events.get().status, Order.Status.SHIPPED)

    def test_invalid_transition_rejected(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {'status': Order.Status.DELIVERED})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_agents_cannot_change_orders(self):
        self.client.force_login(make_user('agent', role='agent'))
        response = self.client.get(self.url)
        self.assertIsNone(response.context['form'])


class AgentAttachmentTests(TestCase):
    def setUp(self):
        self.agent = make_user('agent', role='agent')
        self.ticket = services.create_ticket(make_user('cust'), Ticket.Category.DAMAGED_PRODUCT, 'Broken', 'Cracked')
        self.url = reverse('dashboard:ticket_detail', args=[self.ticket.code])

    def test_agent_reply_with_photo_and_canned_replies(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (10, 10)).save(buf, 'PNG')
        self.client.force_login(self.agent)
        self.assertContains(self.client.get(self.url), 'Canned replies')
        self.client.post(self.url, {'action': 'reply', 'body': 'See label',
                                    'attachments': [SimpleUploadedFile('l.png', buf.getvalue(), 'image/png')]})
        self.assertEqual(self.ticket.attachments.count(), 1)


class SystemStatusTests(TestCase):
    def test_admin_sees_component_status(self):
        self.client.force_login(make_user('boss', role='admin'))
        with self.settings(LLM_PROVIDER='none'):
            response = self.client.get(reverse('dashboard:system'))
        names = [c['name'] for c in response.context['checks']]
        self.assertEqual(names, ['Database', 'AI assistant', 'Email', 'Payments', 'File storage', 'Cache'])
        self.assertTrue(response.context['checks'][0]['ok'])
        self.assertContains(response, 'Rule-based assistant')

    def test_agents_cannot_see_it(self):
        self.client.force_login(make_user('agent', role='agent'))
        self.assertEqual(self.client.get(reverse('dashboard:system')).status_code, 403)
