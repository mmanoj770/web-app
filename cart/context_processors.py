from .cart import SESSION_KEY


def cart(request):
    # Read the session directly so pages that don't touch the cart stay cheap.
    items = request.session.get(SESSION_KEY, {})
    return {'cart_count': sum(items.values())}
