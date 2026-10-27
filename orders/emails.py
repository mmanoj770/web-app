"""Order emails: the customer's confirmation and the store owner's new-order alert."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from catalog.templatetags.store_tags import money

logger = logging.getLogger(__name__)


def _send(subject, template, context, recipients):
    recipients = [r for r in recipients if r]
    if not recipients:
        return
    context = {**context, 'STORE_NAME': settings.STORE_NAME, 'SITE_URL': settings.SITE_URL}
    message = EmailMultiAlternatives(
        f'[{settings.STORE_NAME}] {subject}',
        render_to_string(f'emails/{template}.txt', context),
        settings.DEFAULT_FROM_EMAIL,
        recipients,
    )
    message.attach_alternative(render_to_string(f'emails/{template}.html', context), 'text/html')
    try:
        message.send()
    except Exception:
        # Never fail a paid order because of email; the log shows why (e.g. a wrong App Password).
        logger.exception('Could not send "%s" to %s', subject, ', '.join(recipients))


def _context(order, payment):
    return {
        'order': order,
        'payment': payment,
        'items': list(order.items.all()),
        'order_url': settings.SITE_URL + order.get_absolute_url(),
        'dashboard_url': settings.SITE_URL + reverse('dashboard:order_detail', args=[order.pk]),
    }


def send_order_confirmation(order, payment):
    _send(f'Order {order.number} confirmed', 'order_confirmation', _context(order, payment), [order.user.email])


def send_new_order_alert(order, payment):
    _send(f'New order {order.number} · {money(order.total)}', 'new_order_alert',
          _context(order, payment), settings.ORDER_ALERT_EMAILS)
