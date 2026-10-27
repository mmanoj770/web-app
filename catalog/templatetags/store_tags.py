import json
from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings

register = template.Library()


def indian_grouping(number):
    """Group digits the Indian way: 1234567 -> 12,34,567."""
    digits = str(number)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ','.join(groups) + ',' + tail


@register.filter
def money(value):
    """Format a price as e.g. ₹1,09,999 (paise shown only when non-zero)."""
    if value in (None, ''):
        return ''
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        return value
    sign = '-' if amount < 0 else ''
    amount = abs(amount)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    text = f'{settings.CURRENCY_SYMBOL}{indian_grouping(rupees)}'
    if paise:
        text += f'.{paise:02d}'
    return sign + text


@register.filter
def bs(field):
    """Render a form field with the design system's input classes."""
    widget = field.field.widget
    input_type = getattr(widget, 'input_type', '')
    if input_type in ('checkbox', 'radio'):
        css = 'check-input'
    elif widget.__class__.__name__.endswith('Select'):
        css = 'input select'
    else:
        css = 'input'
    if field.errors:
        css += ' is-invalid'
    return field.as_widget(attrs={'class': css})


@register.filter
def tone(status):
    """Colour tone for order, payment and ticket statuses."""
    return {
        'pending': 'orange',
        'paid': 'blue',
        'shipped': 'blue',
        'out_for_delivery': 'blue',
        'delivered': 'green',
        'cancelled': 'gray',
        'open': 'red',
        'in_progress': 'orange',
        'waiting_customer': 'blue',
        'resolved': 'green',
        'closed': 'gray',
        'success': 'green',
        'failed': 'red',
        'high': 'red',
        'normal': 'gray',
        'low': 'gray',
    }.get(status, 'gray')


# Backwards-compatible name used in earlier templates.
register.filter('status_badge', tone)


@register.filter
def stars(rating):
    """Five star icons for a 0-5 rating, as 'full', 'half' and 'empty' names."""
    try:
        rating = float(rating or 0)
    except (TypeError, ValueError):
        rating = 0
    result = []
    for i in range(1, 6):
        if rating >= i:
            result.append('full')
        elif rating >= i - 0.5:
            result.append('half')
        else:
            result.append('empty')
    return result


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if mapping else None


@register.filter
def to_json(value):
    """JSON for use inside an HTML attribute (autoescaping keeps it safe)."""
    return json.dumps(value)


@register.filter
def messages_data(messages):
    """Django messages as plain dicts, for the JavaScript toast system."""
    levels = {'debug': 'info', 'info': 'info', 'success': 'success', 'warning': 'warning', 'error': 'error'}
    return [{'text': str(m), 'level': levels.get(m.level_tag, 'info')} for m in messages]
