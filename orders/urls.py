from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.order_list, name='list'),
    path('checkout/', views.checkout, name='checkout'),
    path('<int:pk>/', views.order_detail, name='detail'),
    path('<int:pk>/pay/', views.pay, name='pay'),
    path('<int:pk>/confirmed/', views.success, name='success'),
    path('<int:pk>/cancel/', views.cancel, name='cancel'),
]
