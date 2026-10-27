"""Shared fixtures for the test suite."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils.text import slugify

from catalog.models import Category, Product


def make_user(username, role='customer', **extra):
    User = get_user_model()
    user = User.objects.create_user(
        username=username, password='pass12345!', email=f'{username}@example.com', role=role,
        first_name=username.title(), **extra,
    )
    return user


def make_product(name='Test Laptop', price='50000', stock=5, category='Laptops', **extra):
    category, _ = Category.objects.get_or_create(slug=category.lower(), defaults={'name': category})
    if 'mrp' in extra:
        extra['mrp'] = Decimal(extra['mrp'])
    return Product.objects.create(
        category=category, name=name, slug=slugify(name), brand=extra.pop('brand', 'Acme'),
        price=Decimal(price), stock=stock, **extra,
    )


SHIPPING = {
    'full_name': 'Test Customer',
    'phone': '9999999999',
    'address_line': '1 Test Street',
    'city': 'Pune',
    'postal_code': '411001',
}
