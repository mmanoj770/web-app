"""Choose which LLM powers the shopping assistant.

LLM_PROVIDER selects it: auto (default), anthropic, openai, gemini, groq,
openrouter, gateway, ollama or none. "auto" uses the first provider with
credentials, then Vercel AI Gateway (on Vercel it authenticates with the
deployment's own OIDC token, so no key is needed), then a local Ollama server
if one is running, and the rule-based assistant otherwise.

A provider that rejects our credentials (e.g. AI Gateway before billing is set
up) is paused for a while so customers get instant rule-based answers instead
of waiting on a failing request every time.
"""
import json
import logging
import os
import time
import urllib.request
from contextvars import ContextVar
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

ANTHROPIC_DEFAULT_MODEL = 'claude-opus-5-5'

# OpenAI-compatible chat completion APIs: (base URL, API key env var, default model).
# Providers retire models often (Groq dropped llama-3.3-70b-versatile in August 2026 and Google
# dropped gemini-2.0-flash in June 2026), so check the provider's model list and set LLM_MODEL if
# a call comes back with an unknown-model error. /health/ shows the error under "assistant".
OPENAI_COMPATIBLE = {
    'openai': ('https://api.openai.com/v1', 'OPENAI_API_KEY', 'gpt-4o-mini'),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/openai', 'GEMINI_API_KEY', 'gemini-3.8-flash'),
    'groq': ('https://api.groq.com/openai/v1', 'GROQ_API_KEY', 'openai/gpt-oss-120b'),
    'openrouter': ('https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY', 'openai/gpt-4o-mini'),
    'gateway': ('https://ai-gateway.vercel.sh/v1', 'AI_GATEWAY_API_KEY', 'anthropic/claude-haiku-5.5'),
    'ollama': ('http://localhost:11434/v1', '', 'llama3.2'),
}
AUTO_ORDER = ['openai', 'gemini', 'groq', 'openrouter']
OLLAMA_URL = 'http://localhost:11434/v1'

ANTHROPIC_CREDENTIAL_VARS = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_PROFILE',
                             'ANTHROPIC_FEDERATION_RULE_ID')
PROVIDER_LABELS = {'anthropic': 'Claude', 'openai': 'OpenAI', 'gemini': 'Gemini', 'groq': 'Groq',
                   'openrouter': 'OpenRouter', 'gateway': 'Vercel AI Gateway', 'ollama': 'Ollama'}

# The Vercel OIDC token of the current request (set by assistant.middleware on Vercel).
OIDC_TOKEN = ContextVar('vercel_oidc_token', default='')
PAUSE_SECONDS = 15 * 60


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    api_key: str = ''
    base_url: str = ''

    @property
    def label(self):
        return f'{PROVIDER_LABELS.get(self.name, self.name)} · {self.model}'


def anthropic_has_credentials():
    """True if the Anthropic SDK can find credentials (env vars or an `ant auth login` profile)."""
    if settings.LLM_API_KEY and settings.LLM_PROVIDER == 'anthropic':
        return True
    if any(os.environ.get(name) for name in ANTHROPIC_CREDENTIAL_VARS):
        return True
    config_dir = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.isdir(os.path.join(config_dir, 'anthropic'))


def gateway_token():
    """Credentials for Vercel AI Gateway: an API key, or the deployment's OIDC token."""
    return (os.environ.get('AI_GATEWAY_API_KEY') or os.environ.get('VERCEL_OIDC_TOKEN')
            or OIDC_TOKEN.get())


def pause(name, reason, seconds=PAUSE_SECONDS):
    """Stop using a provider for a while (e.g. it rejected our credentials)."""
    cache.set(f'llm-paused:{name}', reason[:300], seconds)
    logger.warning('Assistant: pausing %s for %s s: %s', name, seconds, reason[:300])


def paused(name):
    """The reason a provider is paused, or None."""
    return cache.get(f'llm-paused:{name}')


_ollama_cache = {'checked_at': -60.0, 'models': []}
OLLAMA_CHECK_SECONDS = 30


def ollama_models(base_url=None):
    """Models installed on the local Ollama server ([] if it isn't running). Cached briefly."""
    now = time.monotonic()
    if now - _ollama_cache['checked_at'] < OLLAMA_CHECK_SECONDS:
        return _ollama_cache['models']
    root = (base_url or OLLAMA_URL).rstrip('/').removesuffix('/v1')
    models = []
    try:
        with urllib.request.urlopen(f'{root}/api/tags', timeout=0.5) as response:
            models = [m['name'] for m in json.loads(response.read()).get('models', [])]
    except (OSError, ValueError, KeyError):
        pass
    _ollama_cache.update(checked_at=now, models=models)
    return models


def _pick_ollama_model(models):
    """Prefer the configured model, then our tuned one, then any installed model."""
    if settings.LLM_MODEL:
        return settings.LLM_MODEL
    for preferred in ('mj-assistant:latest', 'qwen2.5:3b'):
        if preferred in models:
            return preferred.removesuffix(':latest')
    return models[0] if models else OPENAI_COMPATIBLE['ollama'][2]


def resolve():
    """Return the ProviderConfig to use, or None for the rule-based assistant."""
    name = (settings.LLM_PROVIDER or 'auto').lower()
    if name == 'none':
        return None
    if name == 'auto':
        # Skip a provider that is paused (it just rejected our credentials) and try the next one,
        # so one bad key means instant answers from the next provider rather than a failed call
        # on every message. Naming a provider explicitly still forces it, pause or not.
        if anthropic_has_credentials() and not paused('anthropic'):
            name = 'anthropic'
        else:
            name = next((p for p in AUTO_ORDER
                         if os.environ.get(OPENAI_COMPATIBLE[p][1]) and not paused(p)), None)
            if name is None and gateway_token() and not paused('gateway'):
                base_url, _key_var, default_model = OPENAI_COMPATIBLE['gateway']
                return ProviderConfig('gateway', settings.LLM_MODEL or default_model, gateway_token(), base_url)
            if name is None:
                models = ollama_models(settings.LLM_BASE_URL or None)
                if not models:
                    return None
                base_url = settings.LLM_BASE_URL or OLLAMA_URL
                return ProviderConfig('ollama', _pick_ollama_model(models), '', base_url)

    if name == 'anthropic':
        if not anthropic_has_credentials():
            logger.warning('LLM_PROVIDER=anthropic but no Anthropic credentials are configured.')
            return None
        return ProviderConfig('anthropic', settings.LLM_MODEL or ANTHROPIC_DEFAULT_MODEL, settings.LLM_API_KEY)

    if name not in OPENAI_COMPATIBLE:
        logger.warning('Unknown LLM_PROVIDER %r; using the rule-based assistant.', name)
        return None
    base_url, key_var, default_model = OPENAI_COMPATIBLE[name]
    api_key = settings.LLM_API_KEY or (os.environ.get(key_var, '') if key_var else '')
    if name == 'gateway':
        api_key = api_key or gateway_token()
    if key_var and not api_key:
        logger.warning('LLM_PROVIDER=%s but %s is not set.', name, key_var)
        return None
    return ProviderConfig(name, settings.LLM_MODEL or default_model, api_key, settings.LLM_BASE_URL or base_url)
