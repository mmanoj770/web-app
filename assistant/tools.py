"""Store actions the shopping assistant can take.

Every function receives the current user (possibly anonymous) and returns
JSON-serialisable data, so the same code serves the Claude tool-use loop and
the rule-based fallback.
"""
from decimal import Decimal, InvalidOperation

from catalog.models import Category, Product
from catalog.views import search_products as catalog_search
from orders.models import Order
from support import lookup
from support import services as support_services
from support.models import Ticket

LOGIN_REQUIRED = {'error': 'The customer is not logged in. Ask them to log in to see orders or raise tickets.'}


def _decimal(value):
    try:
        return Decimal(str(value)) if value not in (None, '') else None
    except InvalidOperation:
        return None


def product_summary(product):
    return {
        'id': product.pk,
        'name': product.name,
        'brand': product.brand,
        'category': product.category.name,
        'price': str(product.price),
        'mrp': str(product.list_price),
        'discount_percent': product.discount_percent,
        'rating': float(product.rating_avg) if product.rating_count else None,
        'rating_count': product.rating_count,
        'in_stock': product.stock > 0,
        'stock': product.stock,
        'highlights': product.highlights,
        'specs': product.specs,
        'url': product.get_absolute_url(),
    }


def search_products(user, query='', category='', min_price=None, max_price=None, sort='relevance', limit=6):
    products = catalog_search(query, category or None, _decimal(min_price), _decimal(max_price))
    products = products.filter(stock__gt=0)
    if sort == 'price_asc':
        products = products.order_by('price')
    elif sort == 'price_desc':
        products = products.order_by('-price')
    elif sort == 'rating':
        products = products.order_by('-rating_avg', '-rating_count')
    limit = max(1, min(int(limit or 6), 10))
    results = [product_summary(p) for p in products[:limit]]
    return {'count': len(results), 'products': results}


def get_product_details(user, product_ids):
    products = Product.objects.available().select_related('category').filter(pk__in=list(product_ids)[:5])
    details = []
    for product in products:
        data = product_summary(product)
        data['description'] = product.description
        details.append(data)
    return {'products': details}


def list_categories(user):
    return {'categories': [{'name': c.name, 'slug': c.slug} for c in Category.objects.all()]}


def _order_data(order, with_events=False):
    data = {
        'order_number': order.number,
        'placed_on': order.created_at.strftime('%d %b %Y'),
        'status': order.get_status_display(),
        'total': str(order.total),
        'items': [f'{item.quantity} x {item.product_name}' for item in order.items.all()],
        'carrier': order.carrier,
        'tracking_number': order.tracking_number,
        'url': order.get_absolute_url(),
    }
    if with_events:
        data['timeline'] = [
            {'date': e.created_at.strftime('%d %b %Y %H:%M'), 'status': e.get_status_display(), 'note': e.note}
            for e in order.events.all()
        ]
    return data


def get_my_orders(user):
    if not user.is_authenticated:
        return LOGIN_REQUIRED
    orders = Order.objects.filter(user=user).prefetch_related('items')[:5]
    return {'orders': [_order_data(o) for o in orders]}


def _find_order(user, order_number):
    digits = ''.join(ch for ch in str(order_number) if ch.isdigit())
    if not digits:
        return None
    return Order.objects.filter(user=user, pk=int(digits)).prefetch_related('items', 'events').first()


def get_order_status(user, order_number):
    if not user.is_authenticated:
        return LOGIN_REQUIRED
    order = _find_order(user, order_number)
    if order is None:
        return {'error': f'No order {order_number} found for this customer.'}
    return _order_data(order, with_events=True)


def get_my_tickets(user):
    if not user.is_authenticated:
        return LOGIN_REQUIRED
    tickets = Ticket.objects.filter(customer=user)[:5]
    return {'tickets': [
        {'ticket_id': t.code, 'subject': t.subject, 'status': t.get_status_display(),
         'opened_on': t.created_at.strftime('%d %b %Y'), 'url': t.get_absolute_url()}
        for t in tickets
    ]}


def create_support_ticket(user, category, subject, description, order_number=None):
    if not user.is_authenticated:
        return LOGIN_REQUIRED
    if category not in Ticket.Category.values:
        return {'error': f'Unknown category. Use one of: {", ".join(Ticket.Category.values)}.'}
    order = None
    if order_number:
        order = _find_order(user, order_number)
        if order is None:
            return {'error': f'No order {order_number} found for this customer.'}
    ticket = support_services.create_ticket(
        customer=user,
        category=category,
        subject=subject[:200],
        description=description,
        order=order,
        source=Ticket.Source.ASSISTANT,
    )
    return {'ticket_id': ticket.code, 'status': ticket.get_status_display(), 'url': ticket.get_absolute_url()}


def search_faqs(user, query):
    faqs = lookup.search_faqs(query, limit=3)
    if not faqs:
        return {'faqs': [], 'note': 'No FAQ matches. If you cannot answer, raise a support ticket.'}
    return {'faqs': [{'question': f.question, 'answer': f.answer} for f in faqs]}


def explain_error_code(user, code):
    found, error = lookup.find_error_code(code)
    if error is None:
        return {'error': f'Unknown error code {found or code}.'}
    return lookup.error_code_data(error)


# Tool definitions for the Claude Messages API, in a fixed order.
TOOL_SPECS = [
    {
        'name': 'search_products',
        'description': (
            'Search the store catalog for in-stock products. Use this for any product discovery, '
            'recommendation or price question. Prices are in Indian rupees.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Keywords, e.g. "gaming laptop" or "noise cancelling".'},
                'category': {'type': 'string', 'description': 'Category slug from list_categories.'},
                'min_price': {'type': 'number'},
                'max_price': {'type': 'number', 'description': "The customer's budget, if they gave one."},
                'sort': {'type': 'string', 'enum': ['relevance', 'price_asc', 'price_desc', 'rating']},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10},
            },
        },
    },
    {
        'name': 'get_product_details',
        'description': 'Get full descriptions and specs for up to 5 products, e.g. to compare them.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'product_ids': {'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 5},
            },
            'required': ['product_ids'],
        },
    },
    {
        'name': 'list_categories',
        'description': 'List the product categories the store sells.',
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_my_orders',
        'description': "List the logged-in customer's five most recent orders with their status.",
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_order_status',
        'description': 'Get the delivery status, tracking details and timeline of one of the customer\'s orders.',
        'input_schema': {
            'type': 'object',
            'properties': {'order_number': {'type': 'string', 'description': 'e.g. ORD-000012'}},
            'required': ['order_number'],
        },
    },
    {
        'name': 'get_my_tickets',
        'description': "List the logged-in customer's recent support tickets and their status.",
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'create_support_ticket',
        'description': (
            'Raise a support ticket for a human agent, with the details the customer gave you in the '
            'description. Use it when the customer asks for help a person must give, or when you cannot '
            'answer their question from the other tools.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'category': {'type': 'string', 'enum': Ticket.Category.values},
                'subject': {'type': 'string', 'description': 'One-line summary.'},
                'description': {'type': 'string'},
                'order_number': {'type': 'string', 'description': 'Related order, if any.'},
            },
            'required': ['category', 'subject', 'description'],
        },
    },
    {
        'name': 'search_faqs',
        'description': ("Search the store's FAQs (delivery, payments, refunds, returns, warranty, support). "
                        'Use it for any policy or how-to question and answer from the results.'),
        'input_schema': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': "The customer's question."}},
            'required': ['query'],
        },
    },
    {
        'name': 'explain_error_code',
        'description': 'Explain an error code the customer saw, such as PAY-001 or WEB-500, and how to fix it.',
        'input_schema': {
            'type': 'object',
            'properties': {'code': {'type': 'string', 'description': 'The code, e.g. PAY-001.'}},
            'required': ['code'],
        },
    },
]

HANDLERS = {
    'search_products': search_products,
    'get_product_details': get_product_details,
    'list_categories': list_categories,
    'get_my_orders': get_my_orders,
    'get_order_status': get_order_status,
    'get_my_tickets': get_my_tickets,
    'create_support_ticket': create_support_ticket,
    'search_faqs': search_faqs,
    'explain_error_code': explain_error_code,
}


def run_tool(user, name, arguments):
    handler = HANDLERS.get(name)
    if handler is None:
        return {'error': f'Unknown tool {name}.'}
    try:
        return handler(user, **(arguments or {}))
    except (TypeError, ValueError) as exc:
        return {'error': f'Invalid arguments: {exc}'}
