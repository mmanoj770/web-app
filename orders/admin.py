from django.contrib import admin

from .models import Order, OrderEvent, OrderItem, Payment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'product_name', 'unit_price', 'quantity')


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('amount', 'status', 'reference', 'card_last4', 'failure_reason', 'created_at')


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ('status', 'note', 'created_at')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'user', 'total', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('id', 'user__username', 'user__email', 'full_name', 'tracking_number')
    inlines = [OrderItemInline, PaymentInline, OrderEventInline]
