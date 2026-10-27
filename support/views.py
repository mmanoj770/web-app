from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .forms import FeedbackForm, ReplyForm, TicketForm
from .models import Ticket

QUICK_HELP = [
    ('missing_delivery', 'truck', 'Where is my order?', 'Track it or report a missing delivery'),
    ('payment_failure', 'credit-card', 'Payment issue', 'Failed or double charged'),
    ('damaged_product', 'box-seam', 'Damaged or wrong item', 'Get a replacement'),
    ('refund', 'arrow-counterclockwise', 'Return or refund', 'Within 7 days of delivery'),
    ('product_question', 'question-circle', 'Product question', 'Before or after you buy'),
    ('other', 'chat-dots', 'Something else', 'We are here to help'),
]


def help_center(request):
    # FAQs are loaded by the page from /api/faqs/.
    context = {'quick_help': QUICK_HELP}
    if request.user.is_authenticated:
        context['recent_orders'] = request.user.orders.prefetch_related('items__product__images')[:3]
        context['open_tickets'] = request.user.tickets.filter(status__in=Ticket.ACTIVE_STATUSES)[:3]
    return render(request, 'support/help_center.html', context)


def faq(request):
    """FAQ page, loaded by the page from /api/faqs/."""
    return render(request, 'support/faq.html')


def error_codes(request):
    """Error code reference, loaded by the page from /api/error-codes/."""
    return render(request, 'support/error_codes.html')


@login_required
def ticket_list(request):
    tab = request.GET.get('tab', 'active')
    tickets = request.user.tickets.select_related('order', 'assigned_to')
    tickets = tickets.filter(status__in=Ticket.ACTIVE_STATUSES) if tab == 'active' else tickets.exclude(
        status__in=Ticket.ACTIVE_STATUSES)
    return render(request, 'support/ticket_list.html', {'tickets': tickets, 'tab': tab})


@login_required
def ticket_create(request):
    initial = {'order': request.GET.get('order'), 'category': request.GET.get('category')}
    form = TicketForm(request.POST or None, request.FILES or None, customer=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        ticket = services.create_ticket(
            customer=request.user, category=data['category'], subject=data['subject'],
            description=data['description'], order=data['order'], attachments=data['attachments'],
        )
        messages.success(request, f'Ticket {ticket.code} created. We will reply by email and on this page.')
        return redirect(ticket)
    return render(request, 'support/ticket_form.html', {
        'form': form,
        'order_categories': [str(c) for c in Ticket.ORDER_CATEGORIES],
        'tips': {
            'payment_failure': 'Most failed payments are reversed by your bank within 5-7 business days.',
            'damaged_product': 'Photos of the item and the box help us arrange a replacement faster.',
            'missing_delivery': 'Please check with neighbours or building security before raising this.',
            'refund': 'Returns are accepted within 7 days of delivery for damaged, defective or wrong items.',
        },
    })


@login_required
def ticket_detail(request, code):
    ticket = get_object_or_404(Ticket.objects.select_related('order', 'assigned_to'),
                               code=code, customer=request.user)
    form = ReplyForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        if ticket.status == Ticket.Status.CLOSED:
            messages.error(request, 'This ticket is closed. Please open a new ticket.')
        else:
            services.add_message(ticket, request.user, form.cleaned_data['body'],
                                 attachments=form.cleaned_data['attachments'])
            messages.success(request, 'Reply sent.')
        return redirect(ticket)
    return render(request, 'support/ticket_detail.html', {
        'ticket': ticket,
        'thread': ticket.messages.filter(is_internal=False).select_related('author').prefetch_related('attachments'),
        'opening_photos': ticket.attachments.filter(message=None),
        'form': form,
        'feedback_form': FeedbackForm(),
    })


@login_required
@require_POST
def ticket_resolve(request, code):
    ticket = get_object_or_404(Ticket, code=code, customer=request.user)
    if ticket.is_active:
        services.set_status(ticket, Ticket.Status.RESOLVED, by=request.user)
        messages.success(request, 'Glad it is sorted! The ticket is marked as resolved.')
    return redirect(ticket)


@login_required
@require_POST
def ticket_feedback(request, code):
    ticket = get_object_or_404(Ticket, code=code, customer=request.user)
    form = FeedbackForm(request.POST)
    if ticket.can_rate and form.is_valid():
        services.record_feedback(ticket, form.cleaned_data['csat_rating'], form.cleaned_data['csat_comment'])
        messages.success(request, 'Thanks for your feedback!')
    return redirect(ticket)
