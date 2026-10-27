from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Product, WishlistItem
from myproject.utils import redirect_next, wants_json

from .cart import Cart


def _quantity(request, default=1):
    try:
        return max(0, int(request.POST.get('quantity', default)))
    except (TypeError, ValueError):
        return default


def cart_detail(request):
    cart = Cart(request)
    lines = cart.lines()
    return render(request, 'cart/cart.html', {'lines': lines, 'summary': cart.summary(lines)})


@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product.objects.available().with_images(), pk=product_id)
    cart = Cart(request)
    if not product.in_stock:
        message, ok = f'Sorry, {product.name} is out of stock.', False
    else:
        cart.add(product, _quantity(request) or 1)
        message, ok = f'Added {product.name} to your bag.', True

    if wants_json(request):
        image = product.primary_image
        return JsonResponse({
            'ok': ok, 'message': message, 'count': len(cart),
            'product': {'name': product.name, 'image': image.thumb_url if image else ''},
        }, status=200 if ok else 409)
    if request.POST.get('buy_now') and ok:
        return redirect('orders:checkout')
    (messages.success if ok else messages.error)(request, message)
    return redirect_next(request, 'cart:detail')


@require_POST
def cart_update(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    quantity = _quantity(request)
    Cart(request).set(product, quantity)
    if quantity > product.stock:
        messages.warning(request, f'Only {product.stock} of {product.name} available.')
    return redirect('cart:detail')


@require_POST
def cart_remove(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    Cart(request).remove(product)
    messages.success(request, f'Removed {product.name} from your bag.')
    return redirect('cart:detail')


@require_POST
def save_for_later(request, product_id):
    """Move an item from the cart to the wishlist."""
    product = get_object_or_404(Product, pk=product_id)
    if not request.user.is_authenticated:
        messages.info(request, 'Log in to save items for later.')
        return redirect('login')
    WishlistItem.objects.get_or_create(user=request.user, product=product)
    Cart(request).remove(product)
    messages.success(request, f'Moved {product.name} to your wishlist.')
    return redirect('cart:detail')
