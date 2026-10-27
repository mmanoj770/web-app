from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
