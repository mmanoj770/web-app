from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.product_list, name='product_list'),
    path('products/<slug:slug>/', views.product_detail, name='product_detail'),
    path('products/<slug:slug>/review/', views.review_create, name='review_create'),
    path('search/suggest/', views.suggest, name='suggest'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('wishlist/<int:product_id>/toggle/', views.wishlist_toggle, name='wishlist_toggle'),
    path('photo-credits/', views.credits, name='credits'),
]
