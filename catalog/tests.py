from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from myproject.testing import make_product


class CatalogTests(TestCase):
    def setUp(self):
        self.cheap = make_product('Budget Laptop', price='35000')
        self.pricey = make_product('Pro Laptop', price='120000')
        self.phone = make_product('Fast Phone', price='20000', category='Smartphones')
        self.hidden = make_product('Old Laptop', price='10000', is_active=False)

    def test_home_page(self):
        response = self.client.get(reverse('catalog:home'))
        self.assertContains(response, 'Budget Laptop')

    def test_filter_by_category_and_price(self):
        response = self.client.get(reverse('catalog:product_list'), {'category': 'laptops', 'max_price': '50000'})
        names = [p.name for p in response.context['page']]
        self.assertEqual(names, ['Budget Laptop'])

    def test_search_matches_category_name(self):
        response = self.client.get(reverse('catalog:product_list'), {'q': 'smartphones'})
        self.assertEqual([p.name for p in response.context['page']], ['Fast Phone'])

    def test_inactive_product_is_hidden(self):
        self.assertEqual(self.client.get(self.hidden.get_absolute_url()).status_code, 404)
        response = self.client.get(reverse('catalog:product_list'))
        self.assertNotIn(self.hidden, list(response.context['page']))

    def test_detail_shows_specs(self):
        self.cheap.specs = {'RAM': '16 GB'}
        self.cheap.save()
        self.assertContains(self.client.get(self.cheap.get_absolute_url()), '16 GB')


class StorefrontFeatureTests(TestCase):
    def setUp(self):
        from accounts.models import User
        self.user = User.objects.create_user('shopper', 'shopper@example.com', 'pass12345!')
        self.phone = make_product('Pixel Phone', price='40000', mrp='50000', category='Smartphones', brand='Google')
        self.iphone = make_product('iPhone', price='70000', mrp='75000', category='Smartphones', brand='Apple')
        self.watch = make_product('Watch', price='20000', category='Smartwatches', brand='Apple')

    def test_discount_and_money_formatting(self):
        from catalog.templatetags.store_tags import money
        self.assertEqual(self.phone.discount_percent, 20)
        self.assertEqual(money(Decimal('109999')), '₹1,09,999')
        self.assertEqual(money(Decimal('999.50')), '₹999.50')

    def test_filter_by_several_brands_and_discount(self):
        url = reverse('catalog:product_list')
        names = lambda r: sorted(p.name for p in r.context['page'])
        self.assertEqual(names(self.client.get(url, {'brand': ['Google', 'Apple'], 'category': 'smartphones'})),
                         ['Pixel Phone', 'iPhone'])
        self.assertEqual(names(self.client.get(url, {'discount': '15'})), ['Pixel Phone'])
        response = self.client.get(url, {'sort': 'discount'})
        self.assertEqual(response.context['page'][0], self.phone)

    def test_brand_facets_count_before_brand_filter(self):
        response = self.client.get(reverse('catalog:product_list'), {'brand': 'Google'})
        facets = {row['brand']: row['n'] for row in response.context['brand_facets']}
        self.assertEqual(facets, {'Apple': 2, 'Google': 1})

    def test_suggest(self):
        data = self.client.get(reverse('catalog:suggest'), {'q': 'pix'}).json()
        self.assertEqual([p['name'] for p in data['products']], ['Pixel Phone'])
        self.assertEqual(self.client.get(reverse('catalog:suggest'), {'q': 'p'}).json()['products'], [])

    def test_wishlist_toggle(self):
        url = reverse('catalog:wishlist_toggle', args=[self.phone.pk])
        self.assertEqual(self.client.post(url, HTTP_ACCEPT='application/json').status_code, 401)
        self.client.force_login(self.user)
        self.assertTrue(self.client.post(url, HTTP_ACCEPT='application/json').json()['saved'])
        self.assertContains(self.client.get(reverse('catalog:wishlist')), 'Pixel Phone')
        self.assertFalse(self.client.post(url, HTTP_ACCEPT='application/json').json()['saved'])

    def test_review_updates_rating(self):
        self.client.force_login(self.user)
        url = reverse('catalog:review_create', args=[self.phone.slug])
        self.client.post(url, {'rating': 4, 'title': 'Good', 'body': 'Nice phone'})
        self.client.post(url, {'rating': 1, 'title': 'Again', 'body': ''})  # Only one review per customer.
        self.phone.refresh_from_db()
        self.assertEqual((self.phone.rating_avg, self.phone.rating_count), (Decimal('4.0'), 1))
        self.assertFalse(self.phone.reviews.get().verified_purchase)

    def test_recently_viewed(self):
        self.client.get(self.phone.get_absolute_url())
        response = self.client.get(self.iphone.get_absolute_url())
        self.assertEqual(list(response.context['recently_viewed']), [self.phone])

    def test_photo_credits_page(self):
        self.assertEqual(self.client.get(reverse('catalog:credits')).status_code, 200)
