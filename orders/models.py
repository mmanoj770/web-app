from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse

DELIVERY_DAYS = 5
TRACKER_STEPS = ['paid', 'shipped', 'out_for_delivery', 'delivered']


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Awaiting payment'
        PAID = 'paid', 'Paid'
        SHIPPED = 'shipped', 'Shipped'
        OUT_FOR_DELIVERY = 'out_for_delivery', 'Out for delivery'
        DELIVERED = 'delivered', 'Delivered'
        CANCELLED = 'cancelled', 'Cancelled'

    # Statuses an administrator can move an order to from each status.
    TRANSITIONS = {
        Status.PENDING: [Status.CANCELLED],
        Status.PAID: [Status.SHIPPED, Status.CANCELLED],
        Status.SHIPPED: [Status.OUT_FOR_DELIVERY, Status.DELIVERED],
        Status.OUT_FOR_DELIVERY: [Status.DELIVERED],
        Status.DELIVERED: [],
        Status.CANCELLED: [],
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    address_line = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=12)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    carrier = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number

    @property
    def number(self):
        return f'ORD-{self.pk:06d}'

    def get_absolute_url(self):
        return reverse('orders:detail', args=[self.pk])

    @property
    def can_cancel(self):
        return self.status == self.Status.PENDING

    @property
    def can_pay(self):
        return self.status == self.Status.PENDING

    def allowed_transitions(self):
        return self.TRANSITIONS.get(self.status, [])

    @property
    def expected_delivery(self):
        """Estimated delivery date: five days after the order was placed."""
        return (self.created_at + timedelta(days=DELIVERY_DAYS)).date()

    def tracker(self):
        """Steps for the delivery progress bar, with the date each one was reached."""
        reached = {}
        for event in self.events.all():
            reached.setdefault(event.status, event.created_at)
        steps = [('placed', 'Ordered', self.created_at)]
        steps += [(status, Order.Status(status).label, reached.get(status)) for status in TRACKER_STEPS]
        current = max((i for i, step in enumerate(steps) if step[2]), default=0)
        return [
            {'key': key, 'label': label, 'date': date, 'done': i <= current, 'current': i == current}
            for i, (key, label, date) in enumerate(steps)
        ]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    # Keep a copy of the name and price so order history survives catalog edits.
    product = models.ForeignKey('catalog.Product', on_delete=models.SET_NULL, null=True, related_name='+')
    product_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    def __str__(self):
        return f'{self.quantity} x {self.product_name}'

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class Payment(models.Model):
    class Status(models.TextChoices):
        SUCCESS = 'success', 'Successful'
        FAILED = 'failed', 'Failed'

    class Method(models.TextChoices):
        UPI = 'upi', 'UPI'
        CARD = 'card', 'Credit / debit card'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CARD)
    status = models.CharField(max_length=10, choices=Status.choices)
    reference = models.CharField(max_length=64, blank=True)
    card_last4 = models.CharField(max_length=4, blank=True)
    upi_id = models.CharField('UPI ID', max_length=100, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    # Customer-facing code for a failed payment, e.g. PAY-001 (see support.ErrorCode).
    error_code = models.CharField(max_length=12, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.order.number} {self.status} {self.amount}'


class OrderEvent(models.Model):
    """One entry in an order's tracking timeline."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='events')
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
