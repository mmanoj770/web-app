from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cart.cart import Cart

from . import services
from .forms import PaymentForm, ShippingForm
from .models import Order

ORDER_TABS = [
    ('all', 'All orders', None),
    ('active', 'In progress', [Order.Status.PENDING, Order.Status.PAID, Order.Status.SHIPPED,
                               Order.Status.OUT_FOR_DELIVERY]),
    ('delivered', 'Delivered', [Order.Status.DELIVERED]),
    ('cancelled', 'Cancelled', [Order.Status.CANCELLED]),
]


def _orders_with_items():
    return Order.objects.prefetch_related('items__product__images')


@login_required
def checkout(request):
    cart = Cart(request)
    lines = cart.lines()
    if not lines:
        messages.info(request, 'Your cart is empty.')
        return redirect('cart:detail')

    user = request.user
    initial = {
        'full_name': user.get_full_name(),
        'phone': user.phone,
        'address_line': user.address_line,
        'city': user.city,
        'postal_code': user.postal_code,
    }
    form = ShippingForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            order = services.place_order(user, cart, form.cleaned_data)
        except services.CheckoutError as exc:
            messages.error(request, str(exc))
            return redirect('cart:detail')
        if request.POST.get('save_address'):
            for field in ('phone', 'address_line', 'city', 'postal_code'):
                setattr(user, field, form.cleaned_data[field])
            user.save(update_fields=['phone', 'address_line', 'city', 'postal_code'])
        return redirect('orders:pay', pk=order.pk)

    return render(request, 'orders/checkout.html', {
        'form': form, 'lines': lines, 'summary': cart.summary(lines), 'step': 1,
    })


@login_required
def pay(request, pk):
    order = get_object_or_404(_orders_with_items(), pk=pk, user=request.user)
    if not order.can_pay:
        return redirect(order)

    form = PaymentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        payment = services.pay_order(order, data['card_number'], method=data['method'], upi_id=data['upi_id'])
        if payment.status == payment.Status.SUCCESS:
            return redirect('orders:success', pk=order.pk)
        messages.error(request, f'Payment failed: {payment.failure_reason} You can try again, or raise a '
                                'support ticket if money was deducted.')
    return render(request, 'orders/pay.html', {'order': order, 'form': form, 'step': 2})


@login_required
def success(request, pk):
    order = get_object_or_404(_orders_with_items(), pk=pk, user=request.user)
    if order.status == Order.Status.PENDING:
        return redirect('orders:pay', pk=order.pk)
    return render(request, 'orders/success.html', {'order': order, 'step': 3})


@login_required
def order_list(request):
    tab = request.GET.get('tab', 'all')
    tabs = {key: statuses for key, _label, statuses in ORDER_TABS}
    orders = _orders_with_items().filter(user=request.user)
    if tabs.get(tab):
        orders = orders.filter(status__in=tabs[tab])
    return render(request, 'orders/order_list.html', {
        'orders': orders, 'tab': tab, 'tabs': [(key, label) for key, label, _s in ORDER_TABS],
    })


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product__images', 'events', 'payments', 'tickets'),
        pk=pk, user=request.user,
    )
    reviewed = set(request.user.reviews.values_list('product_id', flat=True))
    return render(request, 'orders/order_detail.html', {'order': order, 'reviewed': reviewed})


@login_required
@require_POST
def cancel(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)
    if order.can_cancel:
        services.update_status(order, Order.Status.CANCELLED, 'Cancelled by customer.')
        messages.success(request, f'Order {order.number} has been cancelled.')
    else:
        messages.error(request, 'This order can no longer be cancelled. Please raise a support ticket.')
    return redirect(order)
