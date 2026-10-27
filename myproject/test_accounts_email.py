"""Show-password toggle, shared-database setup on Vercel and the email alerts and test email."""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Product
from myproject.testing import make_user
from support import services as support_services

from . import vercel


class PasswordToggleTests(TestCase):
    def test_password_fields_have_a_show_button(self):
        for url in (reverse('login'), reverse('accounts:register')):
            response = self.client.get(url)
            self.assertContains(response, 'data-password-toggle')
            self.assertContains(response, 'class="password-field"')

    def test_change_password_page_uses_store_layout(self):
        self.client.force_login(make_user('pat'))
        response = self.client.get(reverse('password_change'))
        self.assertContains(response, 'data-password-toggle', count=3)
        self.assertContains(response, 'id="ai-panel"')

    @override_settings(SHOW_DEMO_LOGINS=False)
    def test_demo_logins_hidden_on_a_real_database(self):
        self.assertNotContains(self.client.get(reverse('login')), 'Demo logins')


class SharedDatabaseSetupTests(TestCase):
    def test_loads_catalog_into_empty_store_and_creates_admin(self):
        env = {'DJANGO_ADMIN_USERNAME': 'owner', 'DJANGO_ADMIN_PASSWORD': 'Owner-pass-123',
               'DJANGO_ADMIN_EMAIL': 'owner@example.com'}
        with mock.patch.dict('os.environ', env), self.assertLogs('myproject.vercel', 'WARNING'):
            self.assertEqual(vercel.setup_database(), 'done, catalog loaded, admin created')
        self.assertEqual(Product.objects.count(), 29)
        self.assertTrue(Product.objects.filter(images__isnull=False).exists())
        from django.contrib.auth import get_user_model

        owner = get_user_model().objects.get(username='owner')
        self.assertTrue(owner.is_store_admin and owner.check_password('Owner-pass-123'))

        # Running again (every cold start) changes nothing and never resets the password.
        owner.set_password('Changed-pass-456')
        owner.save()
        with mock.patch.dict('os.environ', env):
            self.assertEqual(vercel.setup_database(), 'done')
        self.assertEqual(Product.objects.count(), 29)
        owner.refresh_from_db()
        self.assertTrue(owner.check_password('Changed-pass-456'))


class EmailAlertTests(TestCase):
    @override_settings(TICKET_ALERT_EMAILS=['owner@example.com'])
    def test_owner_gets_new_ticket_alert(self):
        customer = make_user('cara')
        with self.captureOnCommitCallbacks(execute=True):
            ticket = support_services.create_ticket(customer, 'other', 'Gift wrap', 'Can you gift wrap it?')
        alert = next(m for m in mail.outbox if m.to == ['owner@example.com'])
        self.assertEqual(alert.subject, f'[MJ] New ticket {ticket.code}: Gift wrap')
        self.assertIn('cara@example.com', alert.body)
        self.assertIn(f'/dashboard/tickets/{ticket.code}/', alert.body)

    def test_email_failure_does_not_break_tickets(self):
        customer = make_user('dev')
        with mock.patch('support.services.send_mail', side_effect=OSError('SMTP down')), \
                self.assertLogs('support.services', 'ERROR'):
            with self.captureOnCommitCallbacks(execute=True):
                support_services.create_ticket(customer, 'other', 'Hi', 'Question')

    @override_settings(ORDER_ALERT_EMAILS=['owner@example.com'],
                       MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}})
    def test_admin_can_send_test_email(self):
        self.client.force_login(make_user('boss', role='admin'))
        response = self.client.post(reverse('dashboard:test_email'), follow=True)
        self.assertRedirects(response, reverse('dashboard:system'))
        self.assertEqual(mail.outbox[-1].to, ['owner@example.com', 'boss@example.com'])

    def test_test_email_shows_smtp_error(self):
        self.client.force_login(make_user('boss', role='admin'))
        with mock.patch('django.core.mail.send_mail', side_effect=OSError('Username and Password not accepted')):
            response = self.client.post(reverse('dashboard:test_email'), follow=True)
        self.assertContains(response, 'Username and Password not accepted')

    def test_only_admins_can_send_test_email(self):
        self.client.force_login(make_user('agent', role='agent'))
        self.assertEqual(self.client.post(reverse('dashboard:test_email')).status_code, 403)


class SecurityAndPagesTests(TestCase):
    def test_csp_header_and_nonced_inline_scripts(self):
        response = self.client.get(reverse('catalog:home'))
        policy = response['Content-Security-Policy']
        nonce = policy.split("'nonce-")[1].split("'")[0]
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", policy)
        self.assertEqual(response.content.decode().count(f'nonce="{nonce}"'), 2)

    def test_400_page(self):
        from django.test import RequestFactory

        from . import views

        request = RequestFactory().get('/')
        request.user = mock.Mock(is_authenticated=False)
        request.session = {}
        response = views.bad_request(request)
        self.assertContains(response, 'WEB-400', status_code=400)
        self.assertContains(response, 'Ask the assistant', status_code=400)

    def test_feedback_dashboard(self):
        from assistant.models import ChatMessage

        ChatMessage.objects.create(session_key='s', role='user', content='Do you sell drones?')
        ChatMessage.objects.create(session_key='s', role='assistant', content='Not sure.', helpful=False)
        ChatMessage.objects.create(session_key='s', role='assistant', content='Yes!', helpful=True)
        self.client.force_login(make_user('agent', role='agent'))
        response = self.client.get(reverse('dashboard:feedback'))
        self.assertContains(response, '50%')
        self.assertContains(response, 'Do you sell drones?')
        self.client.force_login(make_user('shopper'))
        self.assertEqual(self.client.get(reverse('dashboard:feedback')).status_code, 403)
