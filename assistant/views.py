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
        return JsonResponse({'error': "You're sending messages too quickly. Please wait a minute. (Error AI-429)",
                             'code': 'AI-429'}, status=429)
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
        'messages': [{'id': m.pk, 'role': m.role, 'content': m.content, 'helpful': m.helpful}
                     for m in reversed(messages)],
        'assistant': services.assistant_label(),
    })


@require_POST
def clear(request):
    services.conversation(request).delete()
    return JsonResponse({'ok': True})


@require_POST
def feedback(request):
    """Thumbs up/down on an assistant reply: {"id": <message id>, "helpful": true|false, "comment": ""}."""
    try:
        data = json.loads(request.body)
        message_id, helpful = int(data['id']), data['helpful']
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error': 'Send {"id": ..., "helpful": true|false}.'}, status=400)
    if not isinstance(helpful, bool):
        return JsonResponse({'error': 'helpful must be true or false.'}, status=400)
    if not services.record_feedback(request, message_id, helpful, str(data.get('comment', ''))):
        return JsonResponse({'error': 'Message not found in this conversation.'}, status=404)
    return JsonResponse({'ok': True})
