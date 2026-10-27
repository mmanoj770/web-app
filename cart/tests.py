from django.test import TestCase
from django.urls import reverse

from myproject.testing import make_product


class CartTests(TestCase):
    def setUp(self):
        self.product = make_product(stock=3)

    def test_add_and_view(self):
        self.client.post(reverse('cart:add', args=[self.product.pk]), {'quantity': 2})
        response = self.client.get(reverse('cart:detail'))
        self.assertEqual(response.context['lines'][0]['quantity'], 2)
        self.assertEqual(response.context['cart_count'], 2)

    def test_quantity_is_capped_at_stock(self):
        self.client.post(reverse('cart:add', args=[self.product.pk]), {'quantity': 10})
        response = self.client.get(reverse('cart:detail'))
        self.assertEqual(response.context['lines'][0]['quantity'], 3)

    def test_remove(self):
        self.client.post(reverse('cart:add', args=[self.product.pk]))
        self.client.post(reverse('cart:remove', args=[self.product.pk]))
        self.assertEqual(self.client.get(reverse('cart:detail')).context['lines'], [])

    def test_out_of_stock_cannot_be_added(self):
        self.product.stock = 0
        self.product.save()
        self.client.post(reverse('cart:add', args=[self.product.pk]))
        self.assertEqual(self.client.get(reverse('cart:detail')).context['lines'], [])

    def test_deactivated_product_is_dropped_from_cart(self):
        self.client.post(reverse('cart:add', args=[self.product.pk]))
        self.product.is_active = False
        self.product.save()
        self.assertEqual(self.client.get(reverse('cart:detail')).context['lines'], [])
        self.assertEqual(self.client.session['cart'], {})

    def test_add_redirect_stays_on_site(self):
        response = self.client.post(reverse('cart:add', args=[self.product.pk]), {'next': 'https://evil.example.com'})
        self.assertRedirects(response, reverse('cart:detail'))

    def test_ajax_add_returns_json(self):
        response = self.client.post(reverse('cart:add', args=[self.product.pk]), {'quantity': 2},
                                    HTTP_ACCEPT='application/json')
        self.assertEqual(response.json()['count'], 2)
        self.assertTrue(response.json()['ok'])

    def test_buy_now_goes_to_checkout(self):
        response = self.client.post(reverse('cart:add', args=[self.product.pk]), {'buy_now': '1'})
        self.assertRedirects(response, reverse('orders:checkout'), fetch_redirect_response=False)

    def test_price_summary_shows_savings(self):
        self.product.mrp = 60000
        self.product.save()
        self.client.post(reverse('cart:add', args=[self.product.pk]), {'quantity': 2})
        summary = self.client.get(reverse('cart:detail')).context['summary']
        self.assertEqual((summary['mrp'], summary['discount'], summary['total']), (120000, 20000, 100000))

    def test_save_for_later_moves_to_wishlist(self):
        from myproject.testing import make_user
        user = make_user('saver')
        self.client.force_login(user)
        self.client.post(reverse('cart:add', args=[self.product.pk]))
        self.client.post(reverse('cart:save_for_later', args=[self.product.pk]))
        self.assertEqual(self.client.session['cart'], {})
        self.assertTrue(user.wishlist.filter(product=self.product).exists())
