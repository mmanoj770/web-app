import json

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import services

MAX_MESSAGE_LENGTH = 1000


def _rate_limited(request):
    """Allow ASSISTANT_RATE_LIMIT messages per minute per IP address.

    Each message can trigger paid API calls, so this caps what one client can spend.
    """
    key = f'assistant-rate:{request.META.get("REMOTE_ADDR", "")}'
    cache.add(key, 0, timeout=60)
    try:
        count = cache.incr(key)
    except ValueError:  # The key expired between add() and incr().
        cache.set(key, 1, timeout=60)
        count = 1
    return count > settings.ASSISTANT_RATE_LIMIT


@require_POST
def chat(request):
    if _rate_limited(request):
        return JsonResponse({'error': "You're sending messages too quickly. Please wait a minute."}, status=429)
    try:
        message = json.loads(request.body).get('message', '')
    except (ValueError, AttributeError):
        return JsonResponse({'error': 'Invalid request.'}, status=400)
    message = str(message).strip()[:MAX_MESSAGE_LENGTH]
    if not message:
        return JsonResponse({'error': 'Please type a message.'}, status=400)
    return JsonResponse(services.respond(request, message))


@require_GET
def history(request):
    messages = services.conversation(request).order_by('-created_at', '-pk')[:30]
    return JsonResponse({
        'messages': [{'role': m.role, 'content': m.content} for m in reversed(messages)],
        'assistant': services.assistant_label(),
    })


@require_POST
def clear(request):
    services.conversation(request).delete()
    return JsonResponse({'ok': True})
