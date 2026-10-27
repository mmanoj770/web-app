"""Shopping assistant on any OpenAI-compatible chat completions API.

Works with OpenAI, Google Gemini, Groq, OpenRouter and local models served by
Ollama, LM Studio or vLLM, using the same store tools as the Claude version.
"""
import json
import logging
import urllib.error
import urllib.request

from .llm import MAX_TOOL_ROUNDS, SYSTEM_PROMPT, LLMUnavailable
from .tools import TOOL_SPECS, run_tool

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 90

TOOLS = [
    {'type': 'function',
     'function': {'name': spec['name'], 'description': spec['description'], 'parameters': spec['input_schema']}}
    for spec in TOOL_SPECS
]


def post(config, body):
    headers = {'Content-Type': 'application/json'}
    if config.api_key:
        headers['Authorization'] = f'Bearer {config.api_key}'
    request = urllib.request.Request(
        f'{config.base_url.rstrip("/")}/chat/completions', data=json.dumps(body).encode(), headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors='replace')
        raise LLMUnavailable(f'{config.name} returned HTTP {exc.code}: {detail}') from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMUnavailable(f'Could not reach {config.name}: {exc}') from exc


def chat(history, user, config, send=None):
    """Run one assistant turn. Returns (reply_text, tool_calls) like llm.chat."""
    send = send or post
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, *history]
    tool_calls = []

    for _ in range(MAX_TOOL_ROUNDS):
        data = send(config, {'model': config.model, 'messages': messages, 'tools': TOOLS, 'tool_choice': 'auto'})
        try:
            message = data['choices'][0]['message']
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f'Unexpected response from {config.name}: {str(data)[:200]}') from exc

        calls = message.get('tool_calls') or []
        if not calls:
            text = (message.get('content') or '').strip()
            return text or "Sorry, I didn't catch that. Could you rephrase?", tool_calls

        messages.append({'role': 'assistant', 'content': message.get('content'), 'tool_calls': calls})
        for call in calls:
            function = call.get('function') or {}
            name = function.get('name', '')
            try:
                arguments = json.loads(function.get('arguments') or '{}')
            except json.JSONDecodeError:
                arguments = None
            if isinstance(arguments, dict):
                output = run_tool(user, name, arguments)
            else:
                output = {'error': 'Tool arguments must be a JSON object.'}
            tool_calls.append((name, arguments, output))
            messages.append({'role': 'tool', 'tool_call_id': call.get('id', ''),
                             'content': json.dumps(output, default=str)})

    logger.warning('Assistant stopped after %s tool rounds', MAX_TOOL_ROUNDS)
    return 'Sorry, that took longer than expected. Could you try asking in a simpler way?', tool_calls
