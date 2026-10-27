from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('tickets/', views.ticket_list, name='tickets'),
    path('tickets/<str:code>/', views.ticket_detail, name='ticket_detail'),
    path('orders/', views.order_list, name='orders'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('products/', views.product_list, name='products'),
    path('products/<int:pk>/edit/', views.product_quick_edit, name='product_edit'),
    path('users/', views.user_list, name='users'),
    path('users/<int:pk>/edit/', views.user_update, name='user_edit'),
    path('feedback/', views.feedback, name='feedback'),
    path('system/', views.system_status, name='system'),
    path('system/test-email/', views.send_test_email, name='test_email'),
]
