"""JSON API for the help center: FAQs, error codes and support tickets (CRUD).

Read endpoints are public. Ticket endpoints use the logged-in session and need the
CSRF token (X-CSRFToken header) for POST, PATCH and DELETE, like the rest of the site.
"""
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from myproject.errors import STATUS_CODES  # Error code per HTTP status, shared with the error pages.
from orders.models import Order

from . import lookup, services
from .models import FAQ, ErrorCode, Ticket


def _error(message, status):
    return JsonResponse({'error': message, 'code': STATUS_CODES.get(status, '')}, status=status)


def _body(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@require_GET
def faq_list(request):
    query, category = request.GET.get('q', ''), request.GET.get('category', '')
    faqs = lookup.search_faqs(query, limit=0, category=category)
    return JsonResponse({
        'count': len(faqs),
        'categories': [{'key': key, 'label': label} for key, label in FAQ.Category.choices],
        'results': [lookup.faq_data(faq) for faq in faqs],
    })


@require_GET
def faq_detail(request, pk):
    return JsonResponse(lookup.faq_data(get_object_or_404(FAQ, pk=pk, is_published=True)))


@require_GET
def error_code_list(request):
    codes = ErrorCode.objects.all()
    if request.GET.get('area'):
        codes = codes.filter(area=request.GET['area'])
    return JsonResponse({'count': len(codes), 'results': [lookup.error_code_data(e) for e in codes]})


@require_GET
def error_code_detail(request, code):
    error = ErrorCode.objects.filter(code=code.upper()).first()
    if error is None:
        return _error(f'Unknown error code {code.upper()}.', 404)
    return JsonResponse(lookup.error_code_data(error))


def _ticket_data(ticket, with_messages=False):
    data = {
        'ticket_id': ticket.code, 'subject': ticket.subject, 'description': ticket.description,
        'category': ticket.category, 'status': ticket.status, 'status_label': ticket.get_status_display(),
        'priority': ticket.priority, 'source': ticket.source,
        'order_number': ticket.order.number if ticket.order else None,
        'created_at': ticket.created_at.isoformat(), 'updated_at': ticket.updated_at.isoformat(),
        'url': ticket.get_absolute_url(),
    }
    if with_messages:
        data['messages'] = [
            {'author': m.author.get_full_name() or m.author.username if m.author else 'System',
             'body': m.body, 'created_at': m.created_at.isoformat()}
            for m in ticket.messages.filter(is_internal=False).select_related('author')
        ]
    return data


def _visible_tickets(user):
    return Ticket.objects.select_related('order') if user.is_staff_member else user.tickets.select_related('order')


@require_http_methods(['GET', 'POST'])
def ticket_list(request):
    if not request.user.is_authenticated:
        return _error('Log in to see or raise tickets.', 401)
    if request.method == 'GET':
        tickets = _visible_tickets(request.user)
        if request.GET.get('status'):
            tickets = tickets.filter(status=request.GET['status'])
        return JsonResponse({'results': [_ticket_data(t) for t in tickets[:50]]})

    data = _body(request)
    if data is None:
        return _error('Send a JSON object.', 400)
    category = data.get('category', Ticket.Category.OTHER)
    subject, description = str(data.get('subject', '')).strip(), str(data.get('description', '')).strip()
    if category not in Ticket.Category.values:
        return _error(f'category must be one of: {", ".join(Ticket.Category.values)}.', 400)
    if not subject or not description:
        return _error('subject and description are required.', 400)
    order = None
    if data.get('order_number'):
        digits = ''.join(ch for ch in str(data['order_number']) if ch.isdigit())
        order = Order.objects.filter(pk=int(digits or 0), user=request.user).first()
        if order is None:
            return _error('No such order on your account.', 400)
    ticket = services.create_ticket(customer=request.user, category=category, subject=subject[:200],
                                    description=description, order=order)
    return JsonResponse(_ticket_data(ticket, with_messages=True), status=201)


@require_http_methods(['GET', 'PATCH', 'DELETE'])
def ticket_detail(request, code):
    if not request.user.is_authenticated:
        return _error('Log in to see your tickets.', 401)
    ticket = get_object_or_404(_visible_tickets(request.user), code=code.upper())
    is_owner = ticket.customer_id == request.user.pk

    if request.method == 'GET':
        return JsonResponse(_ticket_data(ticket, with_messages=True))

    if request.method == 'DELETE':
        # Customers can withdraw a ticket nobody has answered yet; administrators can delete any.
        if not (request.user.is_store_admin or (is_owner and ticket.is_active and not ticket.first_response_at)):
            return _error('This ticket can no longer be deleted.', 403)
        services.delete_ticket(ticket)
        return HttpResponse(status=204)

    data = _body(request)
    if data is None:
        return _error('Send a JSON object.', 400)
    if 'status' in data:
        status = data['status']
        allowed = Ticket.Status.values if request.user.is_staff_member else [Ticket.Status.RESOLVED]
        if status not in allowed:
            return _error(f'status must be one of: {", ".join(allowed)}.', 400)
        services.set_status(ticket, status, by=request.user)
    edits = {field: str(data[field]).strip() for field in ('subject', 'description') if field in data}
    if edits:
        if not (is_owner and ticket.status == Ticket.Status.OPEN):
            return _error('Only the customer can edit an open ticket.', 403)
        if not all(edits.values()):
            return _error('subject and description cannot be empty.', 400)
        for field, value in edits.items():
            setattr(ticket, field, value[:200] if field == 'subject' else value)
        ticket.save(update_fields=[*edits, 'updated_at'])
    if 'message' in data and str(data['message']).strip():
        services.add_message(ticket, request.user, str(data['message']).strip())
    ticket.refresh_from_db()
    return JsonResponse(_ticket_data(ticket, with_messages=True))
