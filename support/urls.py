from django.urls import path

from . import views

app_name = 'support'

urlpatterns = [
    path('', views.help_center, name='home'),
    path('faq/', views.faq, name='faq'),
    path('error-codes/', views.error_codes, name='error_codes'),
    path('tickets/', views.ticket_list, name='list'),
    path('new/', views.ticket_create, name='create'),
    path('tickets/<str:code>/', views.ticket_detail, name='detail'),
    path('tickets/<str:code>/resolve/', views.ticket_resolve, name='resolve'),
    path('tickets/<str:code>/feedback/', views.ticket_feedback, name='feedback'),
]
