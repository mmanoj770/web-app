from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F

from catalog.models import Product

from . import emails, payments
from .models import Order, OrderEvent, OrderItem, Payment


class CheckoutError(Exception):
    def __init__(self, message, code=''):
        super().__init__(message)
        self.code = code  # Customer-facing error code, e.g. ORD-001.

    def __str__(self):
        message = super().__str__()
        return f'{message} (Error {self.code})' if self.code else message


@transaction.atomic
def place_order(user, cart, shipping):
    """Create an order from the cart and reserve stock.

    Rows are locked so two customers can't both buy the last unit.
    """
    items = cart.items
    if not items:
        raise CheckoutError('Your cart is empty.', code='ORD-003')

    products = {
        p.pk: p for p in Product.objects.select_for_update().filter(pk__in=items.keys(), is_active=True)
    }
    lines = []
    for product_id, quantity in items.items():
        product = products.get(int(product_id))
        if product is None:
            raise CheckoutError('An item in your cart is no longer available.', code='ORD-002')
        if quantity > product.stock:
            raise CheckoutError(f'Only {product.stock} of {product.name} left in stock.', code='ORD-001')
        lines.append((product, quantity))

    total = sum((product.price * quantity for product, quantity in lines), Decimal('0'))
    order = Order.objects.create(user=user, total=total, **shipping)
    for product, quantity in lines:
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit_price=product.price,
            quantity=quantity,
        )
        Product.objects.filter(pk=product.pk).update(stock=F('stock') - quantity)

    OrderEvent.objects.create(order=order, status=order.status, note='Order placed.')
    cart.clear()
    return order


@transaction.atomic
def pay_order(order, card_number='', method=Payment.Method.CARD, upi_id=''):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if not order.can_pay:
        raise CheckoutError('This order cannot be paid.', code='ORD-004')

    if method == Payment.Method.UPI:
        result = payments.charge_upi(order.total, upi_id)
    else:
        result = payments.charge_card(order.total, card_number)
    payment = Payment.objects.create(
        order=order,
        amount=order.total,
        method=method,
        status=Payment.Status.SUCCESS if result.success else Payment.Status.FAILED,
        reference=result.reference,
        card_last4=payments.normalize_card(card_number)[-4:] if method == Payment.Method.CARD else '',
        upi_id=upi_id.strip().lower() if method == Payment.Method.UPI else '',
        failure_reason=result.failure_reason,
        error_code=result.error_code,
    )
    if result.success:
        # The confirmation email replaces the generic "now: Paid" status email.
        update_status(order, Order.Status.PAID, f'Payment received ({payment.reference}).', notify=False)
        transaction.on_commit(lambda: _notify_paid(order, payment))
    return payment


def _notify_paid(order, payment):
    emails.send_order_confirmation(order, payment)
    emails.send_new_order_alert(order, payment)


@transaction.atomic
def update_status(order, status, note='', carrier='', tracking_number='', notify=True):
    if status == Order.Status.CANCELLED and order.status != Order.Status.CANCELLED:
        _restock(order)
    order.status = status
    if carrier:
        order.carrier = carrier
    if tracking_number:
        order.tracking_number = tracking_number
    order.save()
    OrderEvent.objects.create(order=order, status=status, note=note)
    if notify:
        transaction.on_commit(lambda: _notify_status(order, note))
    return order


def _restock(order):
    for item in order.items.exclude(product=None):
        Product.objects.filter(pk=item.product_id).update(stock=F('stock') + item.quantity)


def _notify_status(order, note):
    if not order.user.email:
        return
    body = f'Your order {order.number} is now: {order.get_status_display()}.'
    if note:
        body += f'\n\n{note}'
    if order.tracking_number:
        body += f'\n\nCarrier: {order.carrier}\nTracking number: {order.tracking_number}'
    send_mail(
        f'[{settings.STORE_NAME}] Order {order.number} update',
        body,
        settings.DEFAULT_FROM_EMAIL,
        [order.user.email],
        fail_silently=True,
    )
