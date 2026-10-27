from django.test import TestCase
from django.urls import reverse

from myproject.testing import make_user

from .models import User


class AccountTests(TestCase):
    def test_register_creates_customer_and_logs_in(self):
        response = self.client.post(reverse('accounts:register'), {
            'username': 'newbie', 'first_name': 'New', 'last_name': 'User', 'email': 'new@example.com',
            'phone': '', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
        })
        self.assertRedirects(response, reverse('catalog:home'))
        user = User.objects.get(username='newbie')
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertFalse(user.is_staff_member)

    def test_register_ignores_external_next(self):
        response = self.client.post(reverse('accounts:register') + '?next=https://evil.example.com', {
            'username': 'newbie', 'first_name': 'New', 'last_name': 'User', 'email': 'new@example.com',
            'phone': '', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
        })
        self.assertRedirects(response, reverse('catalog:home'))

    def test_admin_role_grants_django_admin_access(self):
        admin = make_user('boss', role=User.Role.ADMIN)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_store_admin)

    def test_demoted_admin_loses_django_admin_access(self):
        admin = make_user('boss', role=User.Role.ADMIN)
        admin.role = User.Role.CUSTOMER
        admin.save()
        self.assertFalse(admin.is_staff)

    def test_profile_requires_login(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)
