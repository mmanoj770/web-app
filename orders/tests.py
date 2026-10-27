from django.core import mail
from django.test import TestCase
from django.urls import reverse

from myproject.testing import SHIPPING, make_product, make_user

from .models import Order, Payment

GOOD_CARD = {'method': 'card', 'card_number': '4242 4242 4242 4242', 'name_on_card': 'T', 'expiry': '12/30', 'cvc': '123'}
DECLINED_CARD = dict(GOOD_CARD, card_number='4000 0000 0000 0002')


class CheckoutTests(TestCase):
    def setUp(self):
        self.user = make_user('buyer')
        self.product = make_product(stock=5, price='1000')
        self.client.force_login(self.user)

    def _place_order(self, quantity=2):
        self.client.post(reverse('cart:add', args=[self.product.pk]), {'quantity': quantity})
        response = self.client.post(reverse('orders:checkout'), SHIPPING)
        return Order.objects.latest('pk'), response

    def test_checkout_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('orders:checkout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_checkout_page_prefills_saved_address(self):
        self.user.city = 'Chennai'
        self.user.save()
        self.client.post(reverse('cart:add', args=[self.product.pk]))
        response = self.client.get(reverse('orders:checkout'))
        self.assertContains(response, 'value="Chennai"')
        self.assertContains(response, 'Continue to payment')

    def test_expired_card_is_rejected_before_charging(self):
        order, _ = self._place_order()
        response = self.client.post(reverse('orders:pay', args=[order.pk]), dict(GOOD_CARD, expiry='01/20'))
        self.assertContains(response, 'This card has expired.')
        self.assertFalse(order.payments.exists())

    def test_checkout_creates_order_and_reserves_stock(self):
        order, response = self._place_order(2)
        self.assertRedirects(response, reverse('orders:pay', args=[order.pk]))
        self.assertEqual(order.total, 2000)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(self.client.session['cart'], {})

    def test_checkout_fails_when_stock_ran_out(self):
        self.client.post(reverse('cart:add', args=[self.product.pk]), {'quantity': 4})
        self.product.stock = 1
        self.product.save()
        response = self.client.post(reverse('orders:checkout'), SHIPPING, follow=True)
        self.assertContains(response, 'Only 1 of')
        self.assertFalse(Order.objects.exists())

    def test_successful_payment_marks_order_paid(self):
        order, _ = self._place_order()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('orders:pay', args=[order.pk]), GOOD_CARD)
        self.assertRedirects(response, reverse('orders:success', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertEqual(payment.card_last4, '4242')
        self.assertEqual(order.events.count(), 2)
        self.assertEqual(len(mail.outbox), 1)

    def test_declined_payment_keeps_order_pending(self):
        order, _ = self._place_order()
        response = self.client.post(reverse('orders:pay', args=[order.pk]), DECLINED_CARD)
        self.assertContains(response, 'declined')
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.payments.get().status, Payment.Status.FAILED)

    def test_invalid_card_number_is_rejected(self):
        order, _ = self._place_order()
        self.client.post(reverse('orders:pay', args=[order.pk]), dict(GOOD_CARD, card_number='1234 5678'))
        self.assertEqual(order.payments.get().failure_reason, 'Invalid card number.')

    def test_cancel_restores_stock(self):
        order, _ = self._place_order(2)
        self.client.post(reverse('orders:cancel', args=[order.pk]))
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.product.stock, 5)

    def test_paid_order_cannot_be_cancelled_by_customer(self):
        order, _ = self._place_order()
        self.client.post(reverse('orders:pay', args=[order.pk]), GOOD_CARD)
        self.client.post(reverse('orders:cancel', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)

    def test_customers_cannot_see_each_others_orders(self):
        order, _ = self._place_order()
        self.client.force_login(make_user('snoop'))
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(reverse('orders:pay', args=[order.pk])).status_code, 404)

    def test_upi_payment(self):
        order, _ = self._place_order()
        response = self.client.post(reverse('orders:pay', args=[order.pk]), {'method': 'upi', 'upi_id': 'fail@upi'})
        self.assertContains(response, 'declined')
        response = self.client.post(reverse('orders:pay', args=[order.pk]), {'method': 'upi', 'upi_id': 'me@okbank'})
        self.assertRedirects(response, reverse('orders:success', args=[order.pk]))
        self.assertEqual(order.payments.filter(status='success').get().upi_id, 'me@okbank')
        self.assertContains(self.client.get(reverse('orders:success', args=[order.pk])), 'order is confirmed')

    def test_upi_id_required_for_upi(self):
        order, _ = self._place_order()
        response = self.client.post(reverse('orders:pay', args=[order.pk]), {'method': 'upi', 'upi_id': ''})
        self.assertIn('upi_id', response.context['form'].errors)

    def test_invalid_pin_code_rejected(self):
        self.client.post(reverse('cart:add', args=[self.product.pk]))
        response = self.client.post(reverse('orders:checkout'), dict(SHIPPING, postal_code='12'))
        self.assertIn('postal_code', response.context['form'].errors)

    def test_tracker_marks_reached_steps(self):
        order, _ = self._place_order()
        self.client.post(reverse('orders:pay', args=[order.pk]), GOOD_CARD)
        steps = {s['key']: s for s in order.tracker()}
        self.assertTrue(steps['paid']['done'] and steps['paid']['current'])
        self.assertFalse(steps['shipped']['done'])
