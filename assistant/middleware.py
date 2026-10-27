from django.conf import settings

from .providers import OIDC_TOKEN


class VercelOidcMiddleware:
    """Makes the request's Vercel OIDC token available to the AI Gateway client.

    Vercel adds an `x-vercel-oidc-token` header to every request it forwards to the
    app; AI Gateway accepts it instead of an API key. Only trusted on Vercel.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.ON_VERCEL:
            return self.get_response(request)
        reset = OIDC_TOKEN.set(request.headers.get('x-vercel-oidc-token', ''))
        try:
            return self.get_response(request)
        finally:
            OIDC_TOKEN.reset(reset)
