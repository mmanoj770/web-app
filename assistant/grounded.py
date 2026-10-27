"""Grounded answers for small local models.

Small models (e.g. a 3B model in Ollama) are not reliable at calling tools and
tend to invent products and prices. In grounded mode the backend gathers the
facts itself (using the rule-based assistant and the store tools), and the model
only turns those facts into a friendly reply. A guard rejects replies that
mention prices not in the facts, in which case the rule-based answer is used.
"""
import json
import logging
import re
from decimal import Decimal

from django.conf import settings

from catalog.models import Product
from support import lookup

from . import fallback, tools
from .llm import LLMUnavailable

logger = logging.getLogger(__name__)

MAX_PRODUCTS = 4
ORDER_WORDS = re.compile(r'\b(order|deliver|delivery|arriv|track|shipped|ticket|refund|return|payment|cancel)', re.I)

SYSTEM_PROMPT = f"""You are the friendly shopping assistant for {settings.STORE_NAME}, an online electronics store in India.

Answer the customer's latest message using ONLY the FACTS you are given. Rules:
- Never mention a product, price, order or ticket that is not in FACTS.
- Write prices exactly as they appear in FACTS (for example ₹54,990).
- If FACTS do not answer the question, say so briefly and suggest what the customer can ask, or that they can
  raise a support ticket with the button below your reply.
- The DRAFT ANSWER is correct; you may improve its wording, add helpful detail from FACTS, and answer
  follow-up questions, but do not contradict it.
- Keep replies under 120 words. Use plain sentences and "- " bullet lists. No tables or headings.
- Never write URLs, links or placeholders like [Order URL]: buttons for orders and tickets appear below
  your reply automatically."""


def _price(value):
    from catalog.templatetags.store_tags import money
    return money(Decimal(str(value)))


def _product_facts(product_ids):
    products = Product.objects.available().select_related('category').filter(pk__in=product_ids)
    by_id = {p.pk: p for p in products}
    facts = []
    for pid in product_ids:
        p = by_id.get(pid)
        if not p:
            continue
        fact = {
            'name': p.name, 'brand': p.brand, 'category': p.category.name, 'price': _price(p.price),
            'in_stock': p.in_stock, 'highlights': p.highlights, 'specs': p.specs,
        }
        if p.discount_percent:
            fact['mrp'] = _price(p.list_price)
            fact['discount'] = f'{p.discount_percent}% off'
        if p.rating_count:
            fact['rating'] = f'{p.rating_avg}/5 from {p.rating_count} reviews'
        facts.append(fact)
    return facts


def _named_products(text):
    """Products the customer names directly, e.g. "iphone 15 vs pixel 8"."""
    words = set(re.findall(r'[a-z0-9]+', text)) - fallback.STOPWORDS - fallback.GENERIC_WORDS
    words -= {'pro', 'max', 'plus', 'gen', 'with', 'vs', 'and', 'the', 'compare', 'difference', 'between'}
    if not words:
        return []
    scored = []
    for p in Product.objects.available().only('pk', 'name', 'brand'):
        name_words = set(re.findall(r'[a-z0-9]+', f'{p.name} {p.brand}'.lower()))
        hits = len(words & name_words)
        if hits:
            scored.append((hits, p.pk))
    scored.sort(reverse=True)
    return [pk for _hits, pk in scored[:MAX_PRODUCTS]]


def gather(message, user):
    """Run the rule-based assistant and collect the facts behind its answer."""
    draft = fallback.reply(message, user)
    text = fallback.correct_spelling(message.lower())
    product_ids = list(dict.fromkeys(_named_products(text) + draft['product_ids']))[:MAX_PRODUCTS]
    facts = {
        'store_policies': ['Free delivery on every order: 3-5 business days in metro cities, 5-8 elsewhere.',
                           'Returns within 7 days of delivery for damaged, defective or wrong items.',
                           'Refunds reach the original payment method within 5-7 business days.',
                           'Payments: UPI and credit/debit cards. Failed payments are usually reversed by the bank '
                           'within 5-7 business days.'],
        'customer': user.first_name if user.is_authenticated else 'guest (not logged in)',
    }
    if product_ids:
        facts['products'] = _product_facts(product_ids)
    faqs = lookup.search_faqs(text, limit=2)
    if faqs:
        facts['faqs'] = [{'question': f.question, 'answer': f.answer} for f in faqs]
    _code, error = lookup.find_error_code(message)
    if error:
        facts['error_code'] = lookup.error_code_data(error)
    if ORDER_WORDS.search(text):
        orders = tools.get_my_orders(user)
        facts['orders'] = orders.get('orders') or orders.get('error') or 'No orders yet.'
        if user.is_authenticated:
            facts['support_tickets'] = tools.get_my_tickets(user).get('tickets', [])
    return draft, product_ids, facts


def allowed_amounts(facts, draft_text, message=''):
    """Rupee amounts the reply may mention: those in the facts, the draft and the customer's own message."""
    blob = json.dumps(facts, ensure_ascii=False) + draft_text
    from_message = set()
    for number, unit in re.findall(r'([\d,]+(?:\.\d+)?)\s*(k|lakh)?', message.lower()):
        value = float(number.replace(',', '') or 0)
        value *= {'k': 1000, 'lakh': 100000}.get(unit, 1)
        from_message.add(str(int(value)))
    return from_message | {re.sub(r'\D', '', m) for m in re.findall(r'₹\s?[\d,]+', blob)} | {
        re.sub(r'\D', '', m) for m in re.findall(r'"(?:price|total|mrp)":\s*"?([\d.,]+)', blob)
    }


def is_grounded(reply, facts, draft_text, message=''):
    """Reject replies that mention a price we did not provide."""
    allowed = allowed_amounts(facts, draft_text, message)
    for amount in re.findall(r'(?:₹|rs\.?|inr)\s?([\d,]+(?:\.\d+)?)', reply, re.I):
        digits = re.sub(r'\D', '', amount.split('.')[0])
        if digits and digits not in allowed:
            logger.warning('Assistant reply mentioned an unknown price %s; using the rule-based answer.', amount)
            return False
    return True


def chat(message, history, user, config, send=None):
    """Return the assistant result dict ({reply, product_ids, actions, suggestions})."""
    from . import openai_compat

    send = send or openai_compat.post
    draft, product_ids, facts = gather(message, user)
    prompt = (f'FACTS:\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n\n'
              f'DRAFT ANSWER:\n{draft["reply"]}\n\nCUSTOMER: {message}')
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, *history[:-1], {'role': 'user', 'content': prompt}]
    data = send(config, {'model': config.model, 'messages': messages, 'temperature': 0.3})
    try:
        reply = (data['choices'][0]['message'].get('content') or '').strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f'Unexpected response from {config.name}') from exc

    result = dict(draft)
    reply = tidy(reply)
    if reply and is_grounded(reply, facts, draft['reply'], message):
        result['reply'] = reply
        # Show cards for the products the reply talks about (or the draft's picks).
        mentioned = [pid for pid in product_ids if _mentions(reply, pid)]
        result['product_ids'] = mentioned or draft['product_ids']
    return result


def tidy(reply):
    """Remove links and placeholder URLs; the UI shows real buttons instead."""
    reply = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', reply)  # [text](url) -> text
    reply = re.sub(r'\s*(?:by\s+)?(?:clicking|click)\s+here:?\s*\[[^\]]*\]', ' using the button below', reply, flags=re.I)
    reply = re.sub(r'\s*(?:at|here:?)?\s*\[[^\]]*(?:url|link)[^\]]*\]', '', reply, flags=re.I)
    reply = re.sub(r'https?://\S+', '', reply)
    return re.sub(r'[ \t]+([.,])', r'\1', reply).strip()


def _mentions(reply, product_id):
    from .services import _name_variants
    product = Product.objects.filter(pk=product_id).only('name', 'brand').first()
    return bool(product) and any(v in reply.lower() for v in _name_variants(product.name, product.brand))
