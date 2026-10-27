from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

admin.site.site_header = f'{settings.STORE_NAME} administration'
admin.site.site_title = settings.STORE_NAME

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('cart/', include('cart.urls')),
    path('orders/', include('orders.urls')),
    path('support/', include('support.urls')),
    path('assistant/', include('assistant.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('', include('catalog.urls')),
]

if settings.SERVE_MEDIA:
    # django.conf.urls.static.static() only works with DEBUG on; this also covers Vercel.
    urlpatterns += [
        re_path(rf'^{settings.MEDIA_URL.strip("/")}/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
