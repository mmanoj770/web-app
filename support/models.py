from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

# Hours within which an agent should first reply, by priority.
FIRST_RESPONSE_HOURS = {'high': 4, 'normal': 24, 'low': 48}


class Ticket(models.Model):
    class Category(models.TextChoices):
        MISSING_DELIVERY = 'missing_delivery', 'Missing / late delivery'
        PAYMENT_FAILURE = 'payment_failure', 'Payment failure'
        DAMAGED_PRODUCT = 'damaged_product', 'Damaged or wrong product'
        REFUND = 'refund', 'Return or refund'
        PRODUCT_QUESTION = 'product_question', 'Question about a product'
        OTHER = 'other', 'Something else'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_PROGRESS = 'in_progress', 'In progress'
        WAITING_CUSTOMER = 'waiting_customer', 'Waiting for customer'
        RESOLVED = 'resolved', 'Resolved'
        CLOSED = 'closed', 'Closed'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'

    class Source(models.TextChoices):
        WEB = 'web', 'Help center'
        ASSISTANT = 'assistant', 'AI assistant'

    ACTIVE_STATUSES = [Status.OPEN, Status.IN_PROGRESS, Status.WAITING_CUSTOMER]
    # Categories that need an order to be useful to the support team.
    ORDER_CATEGORIES = [Category.MISSING_DELIVERY, Category.PAYMENT_FAILURE,
                        Category.DAMAGED_PRODUCT, Category.REFUND]

    code = models.CharField(max_length=20, unique=True, editable=False, null=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tickets')
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='tickets')
    category = models.CharField(max_length=30, choices=Category.choices)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.WEB)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='assigned_tickets',
                                    limit_choices_to={'role__in': ['agent', 'admin']})
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Customer satisfaction, asked for once the ticket is resolved.
    csat_rating = models.PositiveSmallIntegerField(null=True, blank=True,
                                                   validators=[MinValueValidator(1), MaxValueValidator(5)])
    csat_comment = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} {self.subject}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.code:
            # The human-readable ID is derived from the primary key, so it is
            # unique and only known after the first insert.
            self.code = f'TKT-{self.pk:06d}'
            Ticket.objects.filter(pk=self.pk).update(code=self.code)

    def get_absolute_url(self):
        return reverse('support:detail', args=[self.code])

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def response_due(self):
        return self.created_at + timedelta(hours=FIRST_RESPONSE_HOURS.get(self.priority, 24))

    @property
    def is_overdue(self):
        """True while an active ticket is still waiting for its first reply past the SLA."""
        return self.is_active and self.first_response_at is None and timezone.now() > self.response_due

    @property
    def can_rate(self):
        return self.status in (self.Status.RESOLVED, self.Status.CLOSED) and self.csat_rating is None

    def progress(self):
        """Steps for the customer's status tracker."""
        steps = [('open', 'Submitted'), ('in_progress', 'Being worked on'), ('resolved', 'Resolved')]
        order = {'open': 0, 'in_progress': 1, 'waiting_customer': 1, 'resolved': 2, 'closed': 2}
        current = order.get(self.status, 0)
        return [{'label': label, 'done': i <= current, 'current': i == current}
                for i, (_key, label) in enumerate(steps)]


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    body = models.TextField()
    # Internal notes are visible to agents and administrators only.
    is_internal = models.BooleanField(default=False)
    # Automatic entries such as status changes.
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.ticket.code} message by {self.author}'


class FAQ(models.Model):
    """A help-center question, served by /api/faqs/ and used by the assistant."""

    class Category(models.TextChoices):
        ORDERS = 'orders', 'Orders & delivery'
        PAYMENTS = 'payments', 'Payments & refunds'
        RETURNS = 'returns', 'Returns & damaged items'
        ACCOUNT = 'account', 'Account & support'

    category = models.CharField(max_length=20, choices=Category.choices)
    question = models.CharField(max_length=200)
    answer = models.TextField()
    # Extra words customers might use, e.g. "late delayed courier", to help matching.
    keywords = models.CharField(max_length=255, blank=True)
    # Offer a ticket of this category alongside the answer (blank: no ticket button).
    ticket_category = models.CharField(max_length=30, choices=Ticket.Category.choices, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'position', 'pk']
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQs'

    def __str__(self):
        return self.question


class ErrorCode(models.Model):
    """A code shown to customers when something fails, e.g. PAY-001 for a declined card."""

    class Area(models.TextChoices):
        PAYMENTS = 'payments', 'Payments'
        ORDERS = 'orders', 'Orders & checkout'
        WEBSITE = 'website', 'Website'
        ASSISTANT = 'assistant', 'AI assistant'
        SUPPORT = 'support', 'Support tickets'

    code = models.CharField(max_length=12, unique=True)
    title = models.CharField(max_length=120)
    area = models.CharField(max_length=20, choices=Area.choices)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    meaning = models.TextField(help_text='What happened, in plain words.')
    resolution = models.TextField(help_text='What the customer can do about it.')
    ticket_category = models.CharField(max_length=30, choices=Ticket.Category.choices, blank=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} {self.title}'

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        super().save(*args, **kwargs)


class TicketAttachment(models.Model):
    """A photo the customer or an agent attached, e.g. of a damaged product."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='attachments')
    # Null for photos added when the ticket was created.
    message = models.ForeignKey(TicketMessage, on_delete=models.CASCADE, null=True, blank=True,
                                related_name='attachments')
    file = models.ImageField(upload_to='tickets/%Y/%m/')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.ticket.code} attachment'
