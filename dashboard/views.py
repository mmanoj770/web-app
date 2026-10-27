from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, staff_required
from catalog.models import Product
from myproject.utils import redirect_next
from orders import services as order_services
from orders.models import Order
from support import services as support_services
from support.models import Ticket

from .forms import AgentReplyForm, OrderStatusForm, ProductQuickEditForm, TicketUpdateForm, UserRoleForm

LOW_STOCK_THRESHOLD = 5
PAID_STATUSES = [Order.Status.PAID, Order.Status.SHIPPED, Order.Status.OUT_FOR_DELIVERY, Order.Status.DELIVERED]

# Canned replies agents can insert and edit before sending.
CANNED_REPLIES = [
    ('Greeting', 'Hi {name}, thanks for reaching out. I am looking into this for you now.'),
    ('Need photos', 'Hi {name}, could you please attach a few photos of the item and the packaging? '
                    'That will help us arrange a replacement quickly.'),
    ('Refund initiated', 'Hi {name}, your refund has been initiated. It will reach your original payment '
                         'method within 5-7 business days.'),
    ('Courier escalation', 'Hi {name}, I have escalated this with our courier partner and will update you '
                           'within 24 hours.'),
    ('Payment reversal', 'Hi {name}, failed payments are reversed by the bank within 5-7 business days. If '
                         'you do not see it by then, reply here and we will follow up with the bank.'),
]


def _querystring(request):
    """Current filters without the page number, for pagination links."""
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def _can_edit_ticket(user, ticket):
    """Admins can edit any ticket; agents only their own or unassigned ones."""
    return user.is_store_admin or ticket.assigned_to_id in (None, user.pk)


@staff_required
def home(request):
    user = request.user
    since = timezone.now() - timedelta(days=30)
    paid = Order.objects.filter(status__in=PAID_STATUSES)
    active = Ticket.objects.filter(status__in=Ticket.ACTIVE_STATUSES)
    rated = Ticket.objects.filter(csat_rating__isnull=False, resolved_at__gte=since)
    context = {
        'overdue_tickets': sum(1 for t in active.filter(first_response_at=None) if t.is_overdue),
        'csat_avg': rated.aggregate(avg=Avg('csat_rating'))['avg'],
        'csat_count': rated.count(),
        'my_open_tickets': Ticket.objects.filter(assigned_to=user, status__in=Ticket.ACTIVE_STATUSES).count(),
        'unassigned_tickets': Ticket.objects.filter(assigned_to=None, status__in=Ticket.ACTIVE_STATUSES).count(),
        'open_tickets': Ticket.objects.filter(status__in=Ticket.ACTIVE_STATUSES).count(),
        'recent_tickets': Ticket.objects.filter(status__in=Ticket.ACTIVE_STATUSES)
                                        .select_related('customer', 'assigned_to')[:5],
    }
    if user.is_store_admin:
        context.update({
            'revenue_30d': paid.filter(created_at__gte=since).aggregate(total=Sum('total'))['total'] or 0,
            'orders_30d': Order.objects.filter(created_at__gte=since).count(),
            'to_ship': Order.objects.filter(status=Order.Status.PAID).count(),
            'low_stock': Product.objects.available().filter(stock__lte=LOW_STOCK_THRESHOLD).order_by('stock')[:8],
            'tickets_by_category': [
                (Ticket.Category(row['category']).label, row['n'])
                for row in Ticket.objects.filter(status__in=Ticket.ACTIVE_STATUSES)
                                         .values('category').annotate(n=Count('id')).order_by('-n')
            ],
        })
    return render(request, 'dashboard/home.html', context)


# --- Tickets -----------------------------------------------------------------

@staff_required
def ticket_list(request):
    view = request.GET.get('view', 'mine')
    status = request.GET.get('status', 'active')
    tickets = Ticket.objects.select_related('customer', 'assigned_to', 'order')

    if view == 'mine':
        tickets = tickets.filter(assigned_to=request.user)
    elif view == 'unassigned':
        tickets = tickets.filter(assigned_to=None)
    if status == 'active':
        tickets = tickets.filter(status__in=Ticket.ACTIVE_STATUSES)
    elif status in Ticket.Status.values:
        tickets = tickets.filter(status=status)

    query = request.GET.get('q', '').strip()
    if query:
        tickets = tickets.filter(
            Q(code__icontains=query) | Q(subject__icontains=query)
            | Q(customer__username__icontains=query) | Q(customer__email__icontains=query)
        )

    page = Paginator(tickets, 20).get_page(request.GET.get('page'))
    return render(request, 'dashboard/ticket_list.html', {
        'page': page, 'view': view, 'status': status, 'query': query,
        'statuses': Ticket.Status.choices, 'querystring': _querystring(request),
    })


@staff_required
def ticket_detail(request, code):
    ticket = get_object_or_404(Ticket.objects.select_related('customer', 'assigned_to', 'order'), code=code)
    can_edit = _can_edit_ticket(request.user, ticket)
    reply_form = AgentReplyForm()
    update_form = TicketUpdateForm(instance=ticket, can_assign=request.user.is_store_admin)

    if request.method == 'POST':
        if not can_edit:
            messages.error(request, 'This ticket is assigned to another agent.')
            return redirect('dashboard:ticket_detail', code=code)
        action = request.POST.get('action')
        if action == 'reply':
            reply_form = AgentReplyForm(request.POST, request.FILES)
            if reply_form.is_valid():
                if ticket.assigned_to is None:
                    ticket.assigned_to = request.user
                    ticket.save(update_fields=['assigned_to', 'updated_at'])
                support_services.add_message(ticket, request.user, **reply_form.cleaned_data)
                messages.success(request, 'Note added.' if reply_form.cleaned_data['is_internal'] else 'Reply sent.')
                return redirect('dashboard:ticket_detail', code=code)
        elif action == 'update':
            old_status = ticket.status
            update_form = TicketUpdateForm(request.POST, instance=ticket, can_assign=request.user.is_store_admin)
            if update_form.is_valid():
                new_status = update_form.cleaned_data['status']
                ticket = update_form.save(commit=False)
                ticket.status = old_status
                ticket.save()
                support_services.set_status(ticket, new_status, by=request.user)
                messages.success(request, 'Ticket updated.')
                return redirect('dashboard:ticket_detail', code=code)
        elif action == 'take':
            ticket.assigned_to = request.user
            ticket.save(update_fields=['assigned_to', 'updated_at'])
            messages.success(request, f'{ticket.code} is now assigned to you.')
            return redirect('dashboard:ticket_detail', code=code)

    name = ticket.customer.first_name or ticket.customer.username
    return render(request, 'dashboard/ticket_detail.html', {
        'ticket': ticket,
        'thread': ticket.messages.select_related('author').prefetch_related('attachments'),
        'opening_photos': ticket.attachments.filter(message=None),
        'canned_replies': [(label, text.format(name=name)) for label, text in CANNED_REPLIES],
        'can_edit': can_edit,
        'reply_form': reply_form,
        'update_form': update_form,
        'other_tickets': ticket.customer.tickets.exclude(pk=ticket.pk)[:5],
    })


# --- Orders ------------------------------------------------------------------

@staff_required
def order_list(request):
    status = request.GET.get('status', '')
    orders = Order.objects.select_related('user')
    if status in Order.Status.values:
        orders = orders.filter(status=status)
    query = request.GET.get('q', '').strip()
    if query:
        digits = ''.join(ch for ch in query if ch.isdigit())
        filters = Q(user__username__icontains=query) | Q(user__email__icontains=query) | Q(full_name__icontains=query)
        if digits:
            filters |= Q(pk=int(digits))
        orders = orders.filter(filters)
    page = Paginator(orders, 20).get_page(request.GET.get('page'))
    return render(request, 'dashboard/order_list.html', {
        'page': page, 'status': status, 'query': query, 'statuses': Order.Status.choices,
        'querystring': _querystring(request),
    })


@staff_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related('user').prefetch_related('items', 'events', 'payments', 'tickets'), pk=pk,
    )
    form = None
    if request.user.is_store_admin and order.allowed_transitions():
        initial = {'carrier': order.carrier, 'tracking_number': order.tracking_number}
        form = OrderStatusForm(request.POST or None, order=order, initial=initial)
        if request.method == 'POST' and form.is_valid():
            data = form.cleaned_data
            order_services.update_status(order, data['status'], data['note'],
                                         data['carrier'], data['tracking_number'])
            messages.success(request, f'{order.number} updated to {order.get_status_display()}.')
            return redirect('dashboard:order_detail', pk=pk)
    return render(request, 'dashboard/order_detail.html', {'order': order, 'form': form})


# --- Products and users (administrators only) --------------------------------

@admin_required
def product_list(request):
    products = Product.objects.select_related('category').prefetch_related('images')
    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(brand__icontains=query))
    if request.GET.get('low_stock'):
        products = products.filter(stock__lte=LOW_STOCK_THRESHOLD)
    page = Paginator(products, 25).get_page(request.GET.get('page'))
    return render(request, 'dashboard/product_list.html', {
        'page': page, 'query': query, 'querystring': _querystring(request),
    })


@admin_required
@require_POST
def product_quick_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductQuickEditForm(request.POST, instance=product)
    if form.is_valid():
        form.save()
        messages.success(request, f'{product.name} updated.')
    else:
        messages.error(request, f'Could not update {product.name}: check the price and stock values.')
    return redirect_next(request, 'dashboard:products')


@admin_required
def user_list(request):
    User = get_user_model()
    users = User.objects.order_by('role', 'username')
    role = request.GET.get('role', '')
    if role in User.Role.values:
        users = users.filter(role=role)
    query = request.GET.get('q', '').strip()
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query)
                             | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    page = Paginator(users, 25).get_page(request.GET.get('page'))
    return render(request, 'dashboard/user_list.html', {
        'page': page, 'role': role, 'query': query, 'roles': User.Role.choices,
        'querystring': _querystring(request),
    })


@admin_required
@require_POST
def user_update(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk)
    if user == request.user:
        messages.error(request, "You can't change your own role or status.")
    else:
        form = UserRoleForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'{user.username} updated.')
    return redirect_next(request, 'dashboard:users')


# --- System status (administrators only) -------------------------------------

@admin_required
@require_POST
def send_test_email(request):
    """Send a test email to the alert addresses and the admin, showing the exact error if it fails."""
    from django.conf import settings
    from django.core.mail import mailers, send_mail

    recipients = list(dict.fromkeys([*settings.ORDER_ALERT_EMAILS, request.user.email]))
    recipients = [r for r in recipients if r]
    backend = mailers.default.__class__.__module__.rsplit('.', 1)[-1]
    if backend in ('console', 'locmem', 'dummy'):
        messages.warning(request, 'Real email is off, so the test email was only printed to the server log. Set '
                                  'EMAIL_HOST_USER and EMAIL_HOST_PASSWORD (a Gmail App Password) and restart.')
    try:
        send_mail(f'[{settings.STORE_NAME}] Test email',
                  f'This is a test from {settings.STORE_NAME} ({settings.SITE_URL}). If you can read it, order and '
                  'ticket emails will reach this inbox.', settings.DEFAULT_FROM_EMAIL, recipients)
    except Exception as exc:  # Show any SMTP problem to the admin.
        messages.error(request, f'Sending failed: {exc.__class__.__name__}: {exc}')
    else:
        if backend not in ('console', 'locmem', 'dummy'):
            messages.success(request, f'Test email sent to {", ".join(recipients)}. Check the inbox and the spam '
                                      'folder.')
    return redirect('dashboard:system')


@admin_required
def system_status(request):
    """Health of each backend component, so admins can see what is live and what is simulated."""
    import platform

    import django
    from django.conf import settings
    from django.core.cache import cache
    from django.core.mail import mailers
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from assistant import providers
    from catalog.models import ProductImage
    from support.models import TicketAttachment

    checks = []

    def add(name, ok, summary, detail='', mode='live'):
        checks.append({'name': name, 'ok': ok, 'summary': summary, 'detail': detail, 'mode': mode})

    # Database: reachable, migrations applied, row counts.
    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        User = get_user_model()
        counts = (f'{Product.objects.count()} products, {Order.objects.count()} orders, '
                  f'{Ticket.objects.count()} tickets, {User.objects.count()} users')
        engine = connection.vendor.capitalize()
        add('Database', not pending, f'{engine} connected',
            f'{counts}. ' + ('All migrations applied.' if not pending else f'{len(pending)} migration(s) pending: '
                                                                          'run "python manage.py migrate".'))
    except Exception as exc:  # Show any database failure on the status page itself.
        add('Database', False, 'Not reachable', str(exc))

    # AI assistant.
    config = providers.resolve()
    if config is None:
        add('AI assistant', True, 'Rule-based assistant (no LLM connected)',
            'Set an API key or run Ollama to use a language model. See README → AI shopping assistant.', 'fallback')
    elif config.name == 'ollama':
        models = providers.ollama_models(config.base_url)
        add('AI assistant', bool(models), f'Local model: {config.model}',
            f'Ollama at {config.base_url} · installed: {", ".join(models) or "none (is `ollama serve` running?)"}')
    else:
        add('AI assistant', True, f'{config.label}', 'Cloud API key configured.')

    # Email.
    backend = mailers.default.__class__.__module__.rsplit('.', 1)[-1]
    alerts = ', '.join(settings.ORDER_ALERT_EMAILS) or 'nobody (set ORDER_ALERT_EMAILS)'
    ticket_alerts = ', '.join(settings.TICKET_ALERT_EMAILS) or 'nobody'
    if backend in ('console', 'locmem', 'dummy'):
        add('Email', False, 'Not sending: emails are only printed to the server log',
            'Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD (a Gmail App Password) to send real emails. '
            f'New-order alerts: {alerts}. New-ticket alerts: {ticket_alerts}.')
    else:
        add('Email', True, f'{backend.upper()} via {mailers.default.host}', 'Order and ticket emails are sent to '
            f'customers. New-order alerts: {alerts}. New-ticket alerts: {ticket_alerts}.')

    # MongoDB (chat transcripts and feedback).
    from myproject import mongo

    mongo_ok, mongo_detail = mongo.ping()
    if mongo_ok is None:
        add('MongoDB', True, 'Not configured', 'Set MONGODB_URI to store chats and feedback in MongoDB. Chats are '
            'kept in the SQL database meanwhile.', 'fallback')
    else:
        stored = ', '.join(f'{n} {name}' for name, n in mongo.counts().items())
        add('MongoDB', bool(mongo_ok), f'{settings.MONGODB_DB} database' if mongo_ok else 'Unreachable',
            f'{stored or "No documents yet"} · {mongo_detail}')

    # Payments.
    add('Payments', True, 'Simulated gateway (UPI and cards)',
        'No real money moves. Replace orders/payments.py with Razorpay or Stripe to take real payments.', 'demo')

    # Media storage.
    photos, attachments = ProductImage.objects.count(), TicketAttachment.objects.count()
    media_ok = settings.MEDIA_ROOT.exists() if hasattr(settings.MEDIA_ROOT, 'exists') else True
    add('File storage', media_ok, f'{photos} product photos, {attachments} ticket photos', str(settings.MEDIA_ROOT))

    # Cache (used by the chat rate limit).
    try:
        cache.set('status-check', 'ok', 5)
        cache_ok = cache.get('status-check') == 'ok'
    except Exception:  # Any cache backend failure.
        cache_ok = False
    cache_name = settings.CACHES['default']['BACKEND'].rsplit('.', 1)[-1] if hasattr(settings, 'CACHES') else ''
    add('Cache', cache_ok, cache_name or 'Local memory', 'Used for the AI chat rate limit.')

    from myproject.observability import RECENT_REQUESTS

    return render(request, 'dashboard/system_status.html', {
        'checks': checks,
        'recent_requests': list(RECENT_REQUESTS)[:50],
        'environment': {
            'Django': django.get_version(),
            'Python': platform.python_version(),
            'Debug mode': 'On (development)' if settings.DEBUG else 'Off (production)',
            'Theme': settings.STORE_THEME,
        },
    })
