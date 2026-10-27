from django.conf import settings

from .models import Category

# Colour themes defined in static/css/store.css: (key, label, swatch gradient).
THEMES = [
    ('mj', 'MJ Classic', 'linear-gradient(135deg, #2c4250 50%, #d5a249 50%)'),
    ('sunset', 'Sunset', 'linear-gradient(135deg, #c2410c, #be185d)'),
    ('ocean', 'Ocean', 'linear-gradient(135deg, #0071e3, #7b3fe4)'),
    ('emerald', 'Emerald', 'linear-gradient(135deg, #047857, #0e7490)'),
    ('royal', 'Royal', 'linear-gradient(135deg, #6d28d9, #a21caf)'),
    ('midnight', 'Midnight (dark)', 'linear-gradient(135deg, #1c1c1e, #3a3a3c)'),
]
THEME_KEYS = [key for key, _label, _swatch in THEMES]


def store(request):
    user = getattr(request, 'user', None)
    return {
        'STORE_NAME': settings.STORE_NAME,
        'CURRENCY': settings.CURRENCY_SYMBOL,
        'ASSET_VERSION': settings.ASSET_VERSION,
        'SHOW_DEMO_LOGINS': settings.SHOW_DEMO_LOGINS,
        'THEMES': THEMES,
        'THEME_KEYS': THEME_KEYS,
        'STORE_THEME': settings.STORE_THEME if settings.STORE_THEME in THEME_KEYS else 'mj',
        'nav_categories': Category.objects.all(),
        'wishlist_count': user.wishlist.count() if user is not None and user.is_authenticated else 0,
    }
