"""Rule-based assistant used when no LLM is configured or the API is unavailable.

It covers the core journeys (product search with a budget, order tracking,
FAQs from the database, error codes such as PAY-001, and escalation to a
ticket) with keyword matching, corrects common typos, and asks a follow-up
question with tappable suggestions when a request is too vague to act on.
When it can't answer a real question, it opens a support ticket for
logged-in customers.
"""
import difflib
import re
from decimal import Decimal

from django.urls import reverse

from catalog.models import Category, Product
from catalog.templatetags.store_tags import money
from support import lookup
from support import services as support_services

from . import tools

STOPWORDS = {
    'a', 'an', 'the', 'i', 'me', 'my', 'want', 'need', 'looking', 'for', 'show', 'find', 'buy', 'get',
    'some', 'any', 'good', 'best', 'cheap', 'please', 'can', 'you', 'is', 'are', 'with', 'and', 'or',
    'under', 'below', 'within', 'less', 'than', 'budget', 'of', 'to', 'in', 'rs', 'inr', 'recommend',
    'suggest', 'something', 'which', 'what', 'do', 'have', 'there', 'around', 'up', 'upto', 'max', 'k',
}

BUDGET_RE = re.compile(
    r'(?:under|below|less than|within|upto|up to|max(?:imum)?|budget(?: of| is)?|around)\s*'
    r'(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(k|thousand|lakh)?',
    re.IGNORECASE,
)

ISSUE_KEYWORDS = {
    'payment_failure': ('payment failed', 'payment fail', 'money deducted', 'amount deducted', 'charged twice',
                        'payment issue', 'payment problem'),
    'damaged_product': ('damaged', 'broken', 'defective', 'not working', 'wrong item', 'wrong product'),
    'refund': ('refund', 'return', 'money back'),
    'missing_delivery': ('not delivered', 'not received', "haven't received", "hasn't arrived", 'not arrived',
                         "didn't arrive", 'did not arrive', 'not yet arrived', 'missing', 'late delivery', 'delayed',
                         'still not', 'not reached'),
}


def _budget(text):
    match = BUDGET_RE.search(text)
    if not match:
        return None
    amount = float(match.group(1).replace(',', ''))
    unit = (match.group(2) or '').lower()
    if unit in ('k', 'thousand'):
        amount *= 1000
    elif unit == 'lakh':
        amount *= 100000
    return amount


# Everyday words customers use for each category slug.
CATEGORY_SYNONYMS = {
    'smartphones': ('phone', 'mobile', 'iphone', 'pixel', 'galaxy s', 'redmi', 'oneplus'),
    'laptops': ('laptop', 'notebook', 'macbook', 'computer'),
    'headphones': ('headphone', 'earbud', 'earphone', 'airpods', 'headset', 'tws', 'noise cancelling'),
    'smartwatches': ('watch', 'fitness band', 'smart band'),
    'tablets': ('tablet', 'ipad', 'tab '),
    'accessories': ('mouse', 'charger', 'ssd', 'storage', 'accessor'),
}
GENERIC_WORDS = {
    'phone', 'mobile', 'smartphone', 'laptop', 'notebook', 'computer', 'headphone', 'earbud', 'earphone',
    'headset', 'tws', 'noise', 'cancelling', 'watch', 'smartwatch', 'fitness', 'band', 'smart', 'tablet', 'tab',
    'storage', 'accessory', 'accessories', 'college', 'student', 'office', 'gaming', 'work', 'study',
}


def _category(text):
    # Specific words first ("headphones" also contains "phone").
    for slug in ('headphones', 'smartwatches', 'tablets', 'laptops', 'accessories', 'smartphones'):
        if any(word in text for word in CATEGORY_SYNONYMS[slug]):
            category = Category.objects.filter(slug=slug).first()
            if category:
                return category
    for category in Category.objects.all():
        names = {category.name.lower(), category.slug.lower(), category.name.lower().rstrip('s')}
        if any(re.search(rf'\b{re.escape(name)}', text) for name in names):
            return category
    return None


def _keywords(text, category):
    words = re.findall(r'[a-z0-9]+', text)
    skip = set(STOPWORDS)
    if category:
        skip |= {category.name.lower(), category.name.lower().rstrip('s'), category.slug}
        # Drop generic words that only told us the category ("phone", "earbuds", ...),
        # but keep model names such as "ipad" or "pixel" as search keywords.
        skip |= GENERIC_WORDS | {w + 's' for w in GENERIC_WORDS}
    return ' '.join(w for w in words if w not in skip and not w.isdigit())


def _ticket_action(category=''):
    url = reverse('support:create')
    if category:
        url += f'?category={category}'
    return {'label': 'Raise a support ticket', 'url': url}


# Words the assistant understands; misspellings are corrected towards these.
INTENT_WORDS = {
    'problem', 'issue', 'help', 'trouble', 'complaint', 'support', 'agent', 'human', 'ticket', 'order', 'orders',
    'delivery', 'delivered', 'deliver', 'track', 'tracking', 'shipping', 'shipped', 'refund', 'return', 'payment',
    'failed', 'deducted', 'charged', 'damaged', 'broken', 'defective', 'wrong', 'missing', 'received', 'cancel',
    'address', 'change', 'policy', 'recommend', 'suggest', 'compare', 'cheap', 'budget', 'under', 'thanks',
    'thank', 'working', 'delayed', 'replacement', 'exchange', 'warranty', 'invoice', 'discount', 'offer',
}
GENERAL_PROBLEM_WORDS = ('problem', 'issue', 'trouble', 'complaint', 'not happy', 'unhappy', 'wrong')
PROBLEM_SUGGESTIONS = ["My order hasn't arrived", 'Payment failed but money was deducted',
                       'I received a damaged item', 'I want to return or get a refund']
START_SUGGESTIONS = ['Best phone under ₹40,000', 'Where is my order?', 'I have a problem with my order',
                     'Return policy']


def _vocabulary():
    words = set(INTENT_WORDS) | GENERIC_WORDS
    for name, brand in Product.objects.available().values_list('name', 'brand'):
        words |= {w for w in re.findall(r'[a-z]+', f'{name} {brand}'.lower()) if len(w) >= 4}
    for synonyms in CATEGORY_SYNONYMS.values():
        words |= {w for phrase in synonyms for w in phrase.split() if len(w) >= 4}
    return words


def correct_spelling(text):
    """Fix likely typos ("probelm" -> "problem", "samsnug" -> "samsung") using the store's vocabulary."""
    vocabulary = _vocabulary()

    def fix(match):
        word = match.group(0)
        if len(word) < 4 or word in vocabulary or word in STOPWORDS:
            return word
        close = difflib.get_close_matches(word, vocabulary, n=1, cutoff=0.8)
        return close[0] if close else word

    return re.sub(r'[a-z]+', fix, text)


def _has_product_signal(text):
    """True if the message names a category, brand, product word or budget."""
    if _budget(text) or _category(text):
        return True
    brands = {b.lower() for b in Product.objects.available().values_list('brand', flat=True)}
    words = set(re.findall(r'[a-z0-9]+', text))
    if words & brands:
        return True
    product_words = set()
    for name in Product.objects.available().values_list('name', flat=True):
        product_words |= {w for w in re.findall(r'[a-z0-9]+', name.lower()) if len(w) >= 3 and not w.isdigit()}
    return bool(words & (product_words - STOPWORDS - {'pro', 'max', 'plus', 'gen'}))


def _recent_orders_line(user):
    if not user.is_authenticated:
        return ''
    data = tools.get_my_orders(user)
    if not data.get('orders'):
        return ''
    latest = data['orders'][0]
    line = f"\n\nYour latest order is **{latest['order_number']}** ({latest['status']})"
    if latest['tracking_number']:
        line += f" with {latest['carrier']}, tracking number {latest['tracking_number']}"
    return line + '.'


# Messages about the customer's own orders or tickets, which need their data rather than an FAQ.
PERSONAL_RE = re.compile(r'\b(where is my|my orders?\b|my tickets?\b|ord-?\s*\d)')


def explain_error(code, error, user):
    """Reply for a message that mentions an error code like PAY-001."""
    result = {'reply': '', 'product_ids': [], 'actions': [], 'suggestions': []}
    if error is None:
        return unsure(f'What does error {code} mean?', user,
                      intro=f"I don't have details for error **{code}** yet.")
    result['reply'] = (f'**{error.code}: {error.title}**\n'
                       f'- What happened: {error.meaning}\n- What to do: {error.resolution}')
    if error.ticket_category:
        result['actions'].append(_ticket_action(error.ticket_category))
    result['actions'].append({'label': 'All error codes', 'url': reverse('support:error_codes')})
    return result


def faq_answer(faq):
    result = {'reply': faq.answer, 'product_ids': [], 'actions': [], 'suggestions': []}
    if faq.ticket_category:
        result['actions'].append(_ticket_action(faq.ticket_category))
    return result


def unsure(message, user, intro="I'm not sure about that one."):
    """When the assistant can't answer: open a ticket for logged-in customers so a person follows up."""
    result = {'reply': '', 'product_ids': [], 'actions': [], 'suggestions': []}
    if not user.is_authenticated:
        result['reply'] = (f'{intro} Log in and I can pass your question to our support team, '
                           'or raise a ticket and an agent will reply.')
        result['actions'] = [{'label': 'Log in', 'url': reverse('login')}, _ticket_action()]
        return result
    ticket, created = support_services.escalate_from_assistant(user, message)
    if created:
        result['reply'] = (f"{intro} I've passed your question to our support team as ticket **{ticket.code}**. "
                           "They'll reply by email and on the ticket page, usually within 24 hours.")
    else:
        result['reply'] = (f"{intro} I've added this to your open ticket **{ticket.code}** so our support "
                           'team sees it.')
    result['actions'] = [{'label': f'View ticket {ticket.code}', 'url': ticket.get_absolute_url()}]
    return result


def _is_real_question(text):
    """At least three words, two of them real-looking words: not "kjh" or "ok"."""
    words = re.findall(r'[a-z]+', text)
    return len(text.split()) >= 3 and sum(1 for w in words if len(w) >= 3 and re.search(r'[aeiou]', w)) >= 2


def reply(message, user):
    """Return {"reply", "product_ids", "actions", "suggestions"} for a customer message."""
    text = correct_spelling(message.lower().strip())
    result = {'reply': '', 'product_ids': [], 'actions': [], 'suggestions': []}

    if re.fullmatch(r'(hi+|hello|hey+|hii+|namaste|good (morning|afternoon|evening))[!. ]*', text):
        result['reply'] = ("Hi! I'm your shopping assistant. I can help you find products, track your orders, "
                           'or sort out a problem. What would you like to do?')
        result['suggestions'] = START_SUGGESTIONS
        return result

    if re.fullmatch(r'(help|help me|i need help|need help|can you help( me)?)[!.? ]*', text):
        result['reply'] = 'Sure, happy to help! What do you need?'
        result['suggestions'] = START_SUGGESTIONS
        return result

    if re.search(r'\b(thanks|thank you|thank u|thx|ty)\b', text):
        result['reply'] = "You're welcome! Is there anything else I can help you with?"
        return result

    if re.fullmatch(r'(bye|goodbye|see you|ok bye)[!. ]*', text):
        result['reply'] = 'Bye! Happy shopping. 👋'
        return result

    if re.search(r'\b(who are you|what can you do|how does this work|what are you)\b', text):
        result['reply'] = ("I'm the store's shopping assistant. I can:\n- recommend products for your budget\n"
                           '- compare products\n- track your orders\n- help with returns, refunds and payment '
                           'problems, and connect you to a human agent')
        result['suggestions'] = START_SUGGESTIONS
        return result

    code, error = lookup.find_error_code(message)
    if code:
        return explain_error(code, error, user)

    if re.search(r'\bcancel(?!l?ing)', text):
        result['reply'] = ('You can cancel an order from **My orders** while it is still awaiting payment. '
                           'Once it has been paid or shipped, raise a ticket and our team will help.')
        result['actions'] = [{'label': 'My orders', 'url': reverse('orders:list')}, _ticket_action('other')]
        return result

    if re.search(r'\b(change|update|wrong)\b.*\baddress\b', text):
        result['reply'] = ('To change the address of an order that has not shipped yet, raise a ticket with the '
                           'new address. For future orders, update it in your profile.')
        result['actions'] = [_ticket_action('other'), {'label': 'Update profile', 'url': reverse('accounts:profile')}]
        return result

    if not PERSONAL_RE.search(text):
        faq = lookup.best_faq(text)
        if faq:
            return faq_answer(faq)

    for category, phrases in ISSUE_KEYWORDS.items():
        if any(p in text for p in phrases):
            result['reply'] = ("I'm sorry about that. Our support team can sort this out for you. "
                               'Raise a ticket and you will get a ticket ID to track it until it is resolved.')
            if category == 'missing_delivery':
                result['reply'] += _recent_orders_line(user)
            if category == 'payment_failure':
                result['reply'] += (' Note: if money was deducted for a failed payment, banks usually '
                                    'reverse it within 5-7 business days.')
            result['actions'].append(_ticket_action(category))
            return result

    # A vague "I have a problem": ask what kind, with one-tap answers.
    if (any(w in text for w in GENERAL_PROBLEM_WORDS) and not _has_product_signal(text)
            and not re.search(r'\b(order|ticket|agent|human)s?\b', text)):
        result['reply'] = ("I'm sorry you're having trouble. I'm here to help! What's the problem about?"
                           + _recent_orders_line(user))
        result['suggestions'] = PROBLEM_SUGGESTIONS
        result['actions'] = [_ticket_action()]
        return result

    if re.search(r'\bproblem|issue|trouble\b', text) and re.search(r'\border', text):
        result['reply'] = ('Sorry about that! Tell me what went wrong with your order so I can point you to '
                           'the fastest fix.' + _recent_orders_line(user))
        result['suggestions'] = PROBLEM_SUGGESTIONS
        return result

    if any(w in text for w in ('human', 'agent', 'ticket', 'complaint', 'support')):
        if 'my ticket' in text or 'ticket status' in text:
            data = tools.get_my_tickets(user)
            if 'error' in data:
                result['reply'] = 'Please log in to see your tickets.'
            elif not data['tickets']:
                result['reply'] = "You don't have any support tickets yet."
            else:
                lines = [f"- {t['ticket_id']}: {t['subject']} ({t['status']})" for t in data['tickets']]
                result['reply'] = 'Your recent tickets:\n' + '\n'.join(lines)
            return result
        result['reply'] = 'You can reach a support agent by raising a ticket. They will reply on the ticket page.'
        result['actions'].append(_ticket_action())
        return result

    if any(w in text for w in ('order', 'deliver', 'track', 'shipping status', 'where is my')):
        order_match = re.search(r'ord-?\s*(\d+)', text)
        if order_match:
            data = tools.get_order_status(user, order_match.group(1))
            if 'error' in data:
                result['reply'] = data['error'] if user.is_authenticated else 'Please log in to track your orders.'
                return result
            orders = [data]
        else:
            data = tools.get_my_orders(user)
            if 'error' in data:
                result['reply'] = 'Please log in so I can look up your orders.'
                return result
            orders = data['orders']
        if not orders:
            result['reply'] = "You haven't placed any orders yet."
            return result
        lines = []
        for o in orders:
            line = f"- {o['order_number']} ({o['placed_on']}): {o['status']}"
            if o['tracking_number']:
                line += f" via {o['carrier']}, tracking {o['tracking_number']}"
            lines.append(line)
        result['reply'] = ('Here is the latest on your orders:\n' + '\n'.join(lines) +
                           '\n\nDelivery usually takes 3-5 business days in metro cities and 5-8 days elsewhere.')
        result['actions'].append({'label': 'View my orders', 'url': reverse('orders:list')})
        return result

    if any(w in text for w in ('return policy', 'refund policy', 'delivery time', 'shipping', 'how long')):
        result['reply'] = ('- Delivery: 3-5 business days in metro cities, 5-8 elsewhere, free on every order.\n'
                           '- Returns: within 7 days of delivery for damaged, defective or wrong items.\n'
                           '- Refunds: back to your original payment method within 5-7 business days.')
        return result

    if not _has_product_signal(text):
        faq = lookup.best_faq(text, strict=False)
        if faq:
            return faq_answer(faq)

    if 'categor' in text or 'what do you sell' in text:
        names = [c['name'] for c in tools.list_categories(user)['categories']]
        result['reply'] = 'We sell: ' + ', '.join(names) + '. What are you shopping for?'
        return result

    if "best deal" in text or 'top deal' in text or 'offers' in text:
        products = Product.objects.available().select_related('category').filter(stock__gt=0)
        deals = [tools.product_summary(p) for p in sorted(products, key=lambda p: p.discount_percent, reverse=True)[:4]]
        result['reply'] = 'Here are the biggest discounts right now:\n' + '\n'.join(
            f"- **{p['name']}**: {money(Decimal(p['price']))} ({p['discount_percent']}% off)" for p in deals)
        result['product_ids'] = [p['id'] for p in deals]
        return result

    # Default: a product search, if the message is about products.
    if not _has_product_signal(text) and not re.search(r'\b(recommend|suggest|buy|show|best|want)\b', text):
        if _is_real_question(text):
            return unsure(message.strip(), user)
        result['reply'] = ("Sorry, I didn't quite get that. I can help you find a product, track an order "
                           'or sort out a problem. Which would you like?')
        result['suggestions'] = START_SUGGESTIONS
        return result
    category = _category(text)
    budget = _budget(text)
    keywords = _keywords(text, category)
    # With a budget, show the best you can get for it; otherwise the best rated.
    sort = 'price_desc' if budget else 'rating'
    data = tools.search_products(user, query=keywords, category=category.slug if category else '',
                                 max_price=budget, sort=sort, limit=4)
    if not data['products'] and keywords and (category or budget):
        # Keywords can be too narrow; retry with just the category and budget.
        data = tools.search_products(user, category=category.slug if category else '', max_price=budget,
                                     sort=sort, limit=4)

    if data['products']:
        intro = 'Here are my top picks'
        if category:
            intro += f' in {category.name}'
        if budget:
            intro += f' within {money(Decimal(str(budget)))}'
        lines = []
        for p in data['products'][:3]:
            line = f"- **{p['name']}**: {money(Decimal(p['price']))}"
            if p['discount_percent']:
                line += f" ({p['discount_percent']}% off)"
            if p['highlights']:
                line += f" · {p['highlights'][0]}"
            lines.append(line)
        result['reply'] = (intro + ':\n' + '\n'.join(lines) +
                           '\n\nTell me your main use (gaming, study, travel...) and I can narrow it down.')
        result['product_ids'] = [p['id'] for p in data['products']]
    elif _has_product_signal(text):
        result['reply'] = ("I couldn't find an exact match. Try a product type and budget, like "
                           '"headphones under 5000".')
        result['suggestions'] = ['Show all smartphones', 'Laptops under ₹60,000', "Today's best deals"]
    else:
        result['reply'] = ("Sorry, I didn't quite get that. I can help you find a product, track an order "
                           'or sort out a problem. Which would you like?')
        result['suggestions'] = START_SUGGESTIONS
    return result
