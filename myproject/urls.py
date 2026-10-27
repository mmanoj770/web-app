from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from orders import views as order_views
from support import api as support_api

from . import observability

admin.site.site_header = f'{settings.STORE_NAME} administration'
admin.site.site_title = settings.STORE_NAME

api_urlpatterns = [
    path('faqs/', support_api.faq_list, name='faqs'),
    path('faqs/<int:pk>/', support_api.faq_detail, name='faq'),
    path('error-codes/', support_api.error_code_list, name='error_codes'),
    path('error-codes/<str:code>/', support_api.error_code_detail, name='error_code'),
    path('tickets/', support_api.ticket_list, name='tickets'),
    path('tickets/<str:code>/', support_api.ticket_detail, name='ticket'),
    path('pincode/<str:pin>/', order_views.pincode, name='pincode'),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', observability.health, name='health'),
    path('api/', include((api_urlpatterns, 'api'))),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('cart/', include('cart.urls')),
    path('orders/', include('orders.urls')),
    path('support/', include('support.urls')),
    path('assistant/', include('assistant.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('', include('catalog.urls')),
]

handler400 = 'myproject.views.bad_request'
handler403 = 'myproject.views.permission_denied'
handler404 = 'myproject.views.page_not_found'
handler500 = 'myproject.views.server_error'

if settings.SERVE_MEDIA:
    # django.conf.urls.static.static() only works with DEBUG on; this also covers Vercel.
    urlpatterns += [
        re_path(rf'^{settings.MEDIA_URL.strip("/")}/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
