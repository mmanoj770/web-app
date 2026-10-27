from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from myproject import mongo

from .models import Ticket, TicketAttachment, TicketMessage

HIGH_PRIORITY_CATEGORIES = {Ticket.Category.PAYMENT_FAILURE, Ticket.Category.MISSING_DELIVERY}
LOW_PRIORITY_CATEGORIES = {Ticket.Category.PRODUCT_QUESTION}


def _priority_for(category):
    if category in HIGH_PRIORITY_CATEGORIES:
        return Ticket.Priority.HIGH
    if category in LOW_PRIORITY_CATEGORIES:
        return Ticket.Priority.LOW
    return Ticket.Priority.NORMAL


def pick_agent():
    """Return the active support agent with the fewest open tickets."""
    User = get_user_model()
    return (
        User.objects.filter(role=User.Role.AGENT, is_active=True)
        .annotate(load=Count('assigned_tickets', filter=Q(assigned_tickets__status__in=Ticket.ACTIVE_STATUSES)))
        .order_by('load', 'pk')
        .first()
    )


@transaction.atomic
def create_ticket(customer, category, subject, description, order=None, source=Ticket.Source.WEB, attachments=()):
    if order is not None and order.user_id != customer.pk:
        raise ValueError('Order does not belong to this customer.')
    ticket = Ticket.objects.create(
        customer=customer,
        order=order,
        category=category,
        subject=subject,
        description=description,
        source=source,
        priority=_priority_for(category),
        assigned_to=pick_agent(),
    )
    _save_attachments(ticket, attachments, customer)
    transaction.on_commit(lambda: _notify(
        [customer.email],
        f'Ticket {ticket.code} received',
        f'We have received your request "{ticket.subject}". Your ticket ID is {ticket.code}.\n'
        'You can track its progress from the Support page.',
    ))
    if ticket.assigned_to:
        agent_email = ticket.assigned_to.email
        transaction.on_commit(lambda: _notify(
            [agent_email], f'New ticket assigned: {ticket.code}', f'{ticket.subject}\n\n{ticket.description}',
        ))
    return ticket


@transaction.atomic
def add_message(ticket, author, body, is_internal=False, attachments=()):
    message = TicketMessage.objects.create(ticket=ticket, author=author, body=body, is_internal=is_internal)
    _save_attachments(ticket, attachments, author, message)
    if is_internal:
        return message

    if author == ticket.customer:
        # A customer reply re-opens a ticket that was waiting on them or resolved.
        if ticket.status in (Ticket.Status.WAITING_CUSTOMER, Ticket.Status.RESOLVED):
            ticket.status = Ticket.Status.IN_PROGRESS if ticket.assigned_to else Ticket.Status.OPEN
            ticket.resolved_at = None
        ticket.save()
        if ticket.assigned_to:
            agent_email = ticket.assigned_to.email
            transaction.on_commit(lambda: _notify(
                [agent_email], f'Customer replied on {ticket.code}', body,
            ))
    else:
        if ticket.status == Ticket.Status.OPEN:
            ticket.status = Ticket.Status.IN_PROGRESS
        if ticket.first_response_at is None:
            ticket.first_response_at = timezone.now()
        ticket.save()
        transaction.on_commit(lambda: _notify(
            [ticket.customer.email], f'New reply on ticket {ticket.code}', body,
        ))
    return message


@transaction.atomic
def set_status(ticket, status, by=None):
    if status == ticket.status:
        return ticket
    ticket.status = status
    ticket.resolved_at = timezone.now() if status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED) else None
    ticket.save()
    TicketMessage.objects.create(
        ticket=ticket, author=by, body=f'Status changed to "{ticket.get_status_display()}".', is_system=True,
    )
    transaction.on_commit(lambda: _notify(
        [ticket.customer.email],
        f'Ticket {ticket.code} is now {ticket.get_status_display()}',
        f'The status of your ticket "{ticket.subject}" changed to {ticket.get_status_display()}.',
    ))
    return ticket


def record_feedback(ticket, rating, comment=''):
    ticket.csat_rating = rating
    ticket.csat_comment = comment
    ticket.save(update_fields=['csat_rating', 'csat_comment', 'updated_at'])
    mongo.insert('feedback', {
        'type': 'ticket', 'ticket_id': ticket.code, 'rating': rating, 'comment': comment,
        'category': ticket.category, 'user_id': ticket.customer_id, 'username': ticket.customer.username,
        'agent': ticket.assigned_to.username if ticket.assigned_to else None,
    })
    return ticket


@transaction.atomic
def delete_ticket(ticket):
    for attachment in ticket.attachments.all():
        attachment.file.delete(save=False)
    ticket.delete()


def escalate_from_assistant(customer, message):
    """Open a ticket for a question the assistant couldn't answer.

    Follow-up questions within 30 minutes are added to the same ticket instead
    of opening new ones. Returns (ticket, created).
    """
    recent = customer.tickets.filter(
        source=Ticket.Source.ASSISTANT, status__in=Ticket.ACTIVE_STATUSES,
        created_at__gte=timezone.now() - timedelta(minutes=30),
    ).first()
    if recent:
        add_message(recent, customer, message)
        return recent, False
    subject = message if len(message) <= 80 else message[:77].rsplit(' ', 1)[0] + '...'
    ticket = create_ticket(
        customer=customer, category=Ticket.Category.OTHER, subject=f'Question: {subject}',
        description=f'{message}\n\n(Raised automatically: the AI assistant was not sure how to answer.)',
        source=Ticket.Source.ASSISTANT,
    )
    return ticket, True


def _save_attachments(ticket, files, uploaded_by, message=None):
    for f in files:
        TicketAttachment.objects.create(ticket=ticket, message=message, file=f, uploaded_by=uploaded_by)


def _notify(recipients, subject, body):
    recipients = [r for r in recipients if r]
    if recipients:
        send_mail(f'[{settings.STORE_NAME}] {subject}', body, settings.DEFAULT_FROM_EMAIL,
                  recipients, fail_silently=True)
