from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class StoreUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('Store profile', {'fields': ('role', 'phone', 'address_line', 'city', 'postal_code')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Store profile', {'fields': ('email', 'role')}),
    )
