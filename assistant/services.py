import logging
import re

import anthropic
from django.conf import settings
from django.urls import reverse

from catalog.models import Product
from myproject import mongo

from . import fallback, grounded, llm, openai_compat, providers
from .models import ChatMessage

logger = logging.getLogger(__name__)

PRODUCT_TOOLS = {'search_products', 'get_product_details'}
OFFLINE_LABEL = 'Smart assistant'
OLLAMA_HISTORY = 6


def _session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def conversation(request):
    return ChatMessage.objects.filter(session_key=_session_key(request))


def assistant_label():
    config = providers.resolve()
    return config.label if config else OFFLINE_LABEL


def _history(request):
    recent = list(conversation(request).order_by('-created_at', '-pk')[:settings.ASSISTANT_HISTORY_LIMIT])
    recent.reverse()
    # Chat APIs require the conversation to start with a user turn.
    while recent and recent[0].role != ChatMessage.Role.USER:
        recent.pop(0)
    return [{'role': m.role, 'content': m.content} for m in recent]


def uses_grounded_mode(config):
    """Small local models answer from facts the backend gathers; capable cloud models call tools."""
    mode = settings.LLM_MODE
    return mode == 'grounded' or (mode == 'auto' and config.name == 'ollama')


def _name_variants(name, brand):
    """Ways a reply might refer to a product, e.g. "Galaxy S24 Ultra" for "Samsung Galaxy S24 Ultra (12 GB)"."""
    short = re.sub(r'\s*\(.*?\)', '', name).strip()
    variants = {name, short}
    if brand and short.lower().startswith(brand.lower() + ' '):
        model = short[len(brand) + 1:]
        variants.add(model)
        # The first two words of the model name, e.g. "MacBook Air" or "Galaxy S24".
        variants.add(' '.join(model.split()[:2]))
    return {v.lower() for v in variants if len(v) >= 5}


def _llm_reply(request, config):
    history = _history(request)
    if config.name == 'ollama':
        # Small local models have short context windows; keep the latest few turns.
        history = history[-OLLAMA_HISTORY:]
        while history and history[0]['role'] != 'user':
            history.pop(0)
    if uses_grounded_mode(config):
        return grounded.chat(history[-1]['content'], history, request.user, config)
    if config.name == 'anthropic':
        text, tool_calls = llm.chat(history, request.user, model=config.model, api_key=config.api_key)
    else:
        text, tool_calls = openai_compat.chat(history, request.user, config)

    # Show cards for products the reply actually mentions.
    seen = {}
    actions = []
    for name, _input, output in tool_calls:
        if name in PRODUCT_TOOLS:
            for product in output.get('products', []):
                seen[product['id']] = _name_variants(product['name'], product.get('brand', ''))
        elif name == 'create_support_ticket' and 'ticket_id' in output:
            actions.append({'label': f"View ticket {output['ticket_id']}", 'url': output['url']})
    lowered = text.lower()
    product_ids = [pid for pid, names in seen.items() if any(n in lowered for n in names)]
    return {'reply': text, 'product_ids': product_ids, 'actions': actions}


def respond(request, message):
    session_key = _session_key(request)
    user = request.user if request.user.is_authenticated else None
    ChatMessage.objects.create(session_key=session_key, user=user, role=ChatMessage.Role.USER, content=message)

    result = None
    label = OFFLINE_LABEL
    config = providers.resolve()
    if config is not None:
        try:
            result = _llm_reply(request, config)
            label = config.label
        except anthropic.AuthenticationError:
            logger.error('Assistant: Anthropic credentials were rejected; using the rule-based assistant.')
        except anthropic.RateLimitError:
            logger.warning('Assistant: rate limited; using the rule-based assistant.')
        except anthropic.APIStatusError as exc:
            logger.error('Assistant: API error %s; using the rule-based assistant.', exc.status_code)
        except anthropic.APIConnectionError:
            logger.warning('Assistant: could not reach the API; using the rule-based assistant.')
        except anthropic.AnthropicError as exc:
            logger.error('Assistant: LLM unavailable (%s); using the rule-based assistant.', exc)
        except llm.LLMUnavailable as exc:
            logger.error('Assistant: %s; using the rule-based assistant.', exc)
    if result is None:
        result = fallback.reply(message, request.user)

    answer = ChatMessage.objects.create(session_key=session_key, user=user, role=ChatMessage.Role.ASSISTANT,
                                        content=result['reply'])
    mongo.insert('chats', {
        'session': session_key, 'message_id': answer.pk, 'user_id': user.pk if user else None,
        'username': user.username if user else None, 'message': message, 'reply': result['reply'],
        'engine': label, 'product_ids': result['product_ids'], 'actions': result['actions'],
        'path': request.headers.get('Referer', ''),
    })
    return {
        'id': answer.pk,
        'reply': result['reply'],
        'products': product_cards(result['product_ids']),
        'actions': result['actions'],
        'suggestions': result.get('suggestions', []),
        'assistant': label,
    }


def record_feedback(request, message_id, helpful, comment=''):
    """Store a thumbs up/down on one of this session's assistant replies (SQL and MongoDB)."""
    answer = conversation(request).filter(pk=message_id, role=ChatMessage.Role.ASSISTANT).first()
    if answer is None:
        return False
    answer.helpful = helpful
    answer.save(update_fields=['helpful'])
    question = conversation(request).filter(role=ChatMessage.Role.USER, pk__lt=answer.pk).order_by('-pk').first()
    user = request.user if request.user.is_authenticated else None
    mongo.insert('feedback', {
        'type': 'chat', 'session': answer.session_key, 'message_id': answer.pk, 'helpful': helpful,
        'comment': comment[:500], 'user_id': user.pk if user else None, 'username': user.username if user else None,
        'question': question.content if question else '', 'reply': answer.content,
    })
    return True


def product_cards(product_ids):
    products = {p.pk: p for p in Product.objects.available().with_images().filter(pk__in=product_ids)}
    cards = []
    for pid in product_ids:
        product = products.get(pid)
        if product:
            image = product.primary_image
            cards.append({
                'name': product.name,
                'price': f'{settings.CURRENCY_SYMBOL}{product.price:,.0f}',
                'mrp': f'{settings.CURRENCY_SYMBOL}{product.list_price:,.0f}' if product.discount_percent else '',
                'discount': product.discount_percent,
                'rating': f'{product.rating_avg}' if product.rating_count else '',
                'url': product.get_absolute_url(),
                'image': image.thumb_url if image else '',
                'add_url': reverse('cart:add', args=[product.pk]),
                'in_stock': product.in_stock,
            })
    return cards
