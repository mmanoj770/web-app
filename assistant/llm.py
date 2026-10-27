"""Claude-powered shopping assistant with tool use (Anthropic SDK)."""
import json
import logging

import anthropic
from django.conf import settings

from .tools import TOOL_SPECS, run_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6

# Models that accept the server-side `fallbacks: "default"` parameter, which
# retries a request on another model if a safety classifier declines it.
FALLBACK_MODELS = {'claude-opus-5-5', 'claude-opus-5', 'claude-fable-5-1', 'claude-sonnet-5-5'}

SYSTEM_PROMPT = f"""You are the shopping assistant for {settings.STORE_NAME}, an online electronics store in India.
You help customers discover and compare products, answer questions about their orders, and get support.

Use the tools to look up products, orders and tickets. Only state prices, stock, specs, order details
and ticket details that come from tool results; if the catalog has nothing suitable, say so rather than
suggesting products the store doesn't sell. Prices are in Indian rupees; write them like ₹54,990.

When recommending, ask about budget and main use if the customer hasn't said, then suggest two or three
options with a one-line reason each, using the exact product names from the tool results. Keep replies
short and friendly, and use plain text with simple "- " bullet lists and **bold** (no tables or headings).

Store policies:
- Delivery: 3-5 business days in metro cities, 5-8 days elsewhere. Free delivery on every order.
- Returns: within 7 days of delivery for damaged, defective or wrong items.
- Refunds: processed to the original payment method within 5-7 business days after approval.
- Payments: UPI and credit/debit cards. If a payment failed but money was deducted, it is normally
  reversed by the bank within 5-7 days; otherwise raise a ticket.

If you can't resolve a problem yourself (missing or damaged delivery, payment failures, refunds,
anything needing a human), offer to raise a support ticket. Confirm with the customer before creating
it, then share the ticket ID. Guests must log in before you can look up orders or raise tickets."""


class LLMUnavailable(Exception):
    """The configured LLM could not produce a reply (network, auth or API error)."""


def _request_kwargs(model):
    kwargs = {
        'model': model,
        'max_tokens': 16000,
        'system': SYSTEM_PROMPT,
        'tools': TOOL_SPECS,
        # Chat replies don't need deep reasoning; low effort keeps them fast and cheap.
        'output_config': {'effort': 'low'},
    }
    if model in FALLBACK_MODELS:
        kwargs['betas'] = ['server-side-fallback-2026-07-01']
        kwargs['fallbacks'] = 'default'
    return kwargs


def chat(history, user, model, api_key='', client=None):
    """Run one assistant turn with Claude.

    `history` is a list of {"role", "content"} text messages ending with the
    customer's latest message. Returns (reply_text, tool_calls) where
    tool_calls is a list of (name, input, result) tuples.
    """
    client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
    messages = list(history)
    tool_calls = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.beta.messages.create(messages=messages, **_request_kwargs(model))

        if response.stop_reason == 'refusal':
            return ("Sorry, I can't help with that request. "
                    'You can contact our support team from the Help center.'), tool_calls

        if response.stop_reason != 'tool_use':
            text = '\n'.join(block.text for block in response.content if block.type == 'text').strip()
            return text or "Sorry, I didn't catch that. Could you rephrase?", tool_calls

        # Keep the full assistant content (including thinking blocks) for the next round.
        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for block in response.content:
            if block.type != 'tool_use':
                continue
            output = run_tool(user, block.name, block.input)
            tool_calls.append((block.name, block.input, output))
            results.append({
                'type': 'tool_result',
                'tool_use_id': block.id,
                'content': json.dumps(output, default=str),
                'is_error': 'error' in output,
            })
        messages.append({'role': 'user', 'content': results})

    logger.warning('Assistant stopped after %s tool rounds', MAX_TOOL_ROUNDS)
    return 'Sorry, that took longer than expected. Could you try asking in a simpler way?', tool_calls
