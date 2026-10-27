from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, FloatField, Q
from django.db.models.functions import Cast, Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from myproject.utils import redirect_next, wants_json

from .forms import ReviewForm
from .models import Category, Product, ProductImage, WishlistItem

SORT_OPTIONS = {
    'relevance': ('Relevance', ['-is_featured', '-rating_count', 'name']),
    'popular': ('Popularity', ['-rating_count', '-rating_avg']),
    'rating': ('Customer rating', ['-rating_avg', '-rating_count']),
    'price_asc': ('Price: low to high', ['price']),
    'price_desc': ('Price: high to low', ['-price']),
    'discount': ('Biggest discount', ['-discount', 'price']),
    'newest': ('Newest first', ['-created_at']),
}
RECENTLY_VIEWED_KEY = 'recently_viewed'


def _decimal_or_none(value):
    try:
        return Decimal(value) if value else None
    except InvalidOperation:
        return None


def with_discount(products):
    """Annotate the discount fraction so listings can sort and filter on it.

    Computed as floats: SQLite stores whole-rupee prices as integers, and
    integer division would round every discount down to zero.
    """
    mrp = Cast(Coalesce('mrp', 'price'), FloatField())
    return products.annotate(discount=(mrp - Cast('price', FloatField())) / mrp)


def search_products(query='', category=None, min_price=None, max_price=None, brands=None):
    """Shared product search used by the catalog pages and the AI assistant."""
    products = Product.objects.available().select_related('category').with_images()
    if query:
        for term in query.split():
            products = products.filter(
                Q(name__icontains=term)
                | Q(brand__icontains=term)
                | Q(description__icontains=term)
                | Q(category__name__icontains=term)
            )
    if category:
        products = products.filter(Q(category__slug=category) | Q(category__name__iexact=category))
    if brands:
        products = products.filter(brand__in=brands)
    if min_price is not None:
        products = products.filter(price__gte=min_price)
    if max_price is not None:
        products = products.filter(price__lte=max_price)
    return products


def _wishlist_ids(request):
    if not request.user.is_authenticated:
        return set()
    return set(request.user.wishlist.values_list('product_id', flat=True))


def _recently_viewed(request, exclude=None):
    ids = [pid for pid in request.session.get(RECENTLY_VIEWED_KEY, []) if pid != exclude]
    products = {p.pk: p for p in Product.objects.available().with_images().filter(pk__in=ids)}
    return [products[pid] for pid in ids if pid in products]


def home(request):
    available = Product.objects.available().with_images().select_related('category')
    return render(request, 'catalog/home.html', {
        'hero_products': available.filter(is_featured=True).order_by('-price')[:3],
        'categories': Category.objects.annotate(product_count=Count('products')).order_by('position', 'name'),
        'deals': with_discount(available.filter(stock__gt=0)).order_by('-discount')[:10],
        'top_rated': available.filter(rating_count__gte=2).order_by('-rating_avg', '-rating_count')[:10],
        'new_arrivals': available.order_by('-created_at')[:10],
        'recently_viewed': _recently_viewed(request)[:10],
        'brands': available.values_list('brand', flat=True).distinct().order_by('brand'),
        'wishlist_ids': _wishlist_ids(request),
    })


def product_list(request):
    query = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '')
    brands = request.GET.getlist('brand')
    min_price = _decimal_or_none(request.GET.get('min_price'))
    max_price = _decimal_or_none(request.GET.get('max_price'))
    min_rating = _decimal_or_none(request.GET.get('rating'))
    min_discount = _decimal_or_none(request.GET.get('discount'))
    in_stock = request.GET.get('in_stock') == '1'
    sort = request.GET.get('sort', 'relevance')
    if sort not in SORT_OPTIONS:
        sort = 'relevance'

    # Facets are counted before the brand filter so customers can pick several brands.
    base = with_discount(search_products(query, category_slug or None, min_price, max_price))
    if min_rating:
        base = base.filter(rating_avg__gte=min_rating)
    if min_discount:
        base = base.filter(discount__gte=float(min_discount) / 100)
    if in_stock:
        base = base.filter(stock__gt=0)
    brand_facets = base.values('brand').annotate(n=Count('id')).order_by('brand')
    products = base.filter(brand__in=brands) if brands else base
    products = products.order_by(*SORT_OPTIONS[sort][1])

    page = Paginator(products, 12).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    active_filters = len(brands) + sum(bool(v) for v in (min_price, max_price, min_rating, min_discount, in_stock))

    return render(request, 'catalog/product_list.html', {
        'page': page,
        'query': query,
        'category': Category.objects.filter(slug=category_slug).first(),
        'categories': Category.objects.annotate(product_count=Count('products')).order_by('position', 'name'),
        'brand_facets': brand_facets,
        'selected_brands': brands,
        'min_price': min_price,
        'max_price': max_price,
        'min_rating': request.GET.get('rating', ''),
        'min_discount': request.GET.get('discount', ''),
        'in_stock': in_stock,
        'sort': sort,
        'sort_options': [(key, label) for key, (label, _order) in SORT_OPTIONS.items()],
        'active_filters': active_filters,
        'querystring': params.urlencode(),
        'wishlist_ids': _wishlist_ids(request),
    })


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.available().select_related('category').prefetch_related('images'), slug=slug,
    )
    viewed = [product.pk] + [pid for pid in request.session.get(RECENTLY_VIEWED_KEY, []) if pid != product.pk]
    request.session[RECENTLY_VIEWED_KEY] = viewed[:12]

    reviews = product.reviews.select_related('user')
    breakdown = {row['rating']: row['n'] for row in reviews.values('rating').annotate(n=Count('id'))}
    total = sum(breakdown.values()) or 1
    rating_bars = [(stars, breakdown.get(stars, 0), breakdown.get(stars, 0) * 100 // total) for stars in range(5, 0, -1)]

    user_review = None
    can_review = False
    if request.user.is_authenticated:
        user_review = reviews.filter(user=request.user).first()
        can_review = user_review is None

    return render(request, 'catalog/product_detail.html', {
        'product': product,
        'images': list(product.images.all()),
        'reviews': reviews[:10],
        'rating_bars': rating_bars,
        'review_form': ReviewForm(),
        'can_review': can_review,
        'user_review': user_review,
        'similar': Product.objects.available().with_images().filter(category=product.category)
                                  .exclude(pk=product.pk).order_by('-rating_avg')[:10],
        'recently_viewed': _recently_viewed(request, exclude=product.pk)[:10],
        'in_wishlist': product.pk in _wishlist_ids(request),
        'wishlist_ids': _wishlist_ids(request),
    })


@require_GET
def suggest(request):
    """Live search suggestions for the header search box."""
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'products': [], 'categories': []})
    products = search_products(query).order_by('-rating_count')[:6]
    categories = Category.objects.filter(name__icontains=query)[:3]
    return JsonResponse({
        'products': [{
            'name': p.name, 'url': p.get_absolute_url(), 'price': f'{p.price:,.0f}',
            'image': p.primary_image.thumb_url if p.primary_image else '', 'category': p.category.name,
        } for p in products],
        'categories': [{'name': c.name, 'url': c.get_absolute_url()} for c in categories],
    })


@login_required
def wishlist(request):
    items = request.user.wishlist.select_related('product__category').prefetch_related('product__images')
    return render(request, 'catalog/wishlist.html', {
        'items': items, 'wishlist_ids': {item.product_id for item in items},
    })


@require_POST
def wishlist_toggle(request, product_id):
    if not request.user.is_authenticated:
        if wants_json(request):
            return JsonResponse({'login_required': True}, status=401)
        return redirect('login')
    product = get_object_or_404(Product, pk=product_id)
    item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
    if not created:
        item.delete()
    message = f'Saved {product.name} to your wishlist.' if created else f'Removed {product.name} from your wishlist.'
    if wants_json(request):
        return JsonResponse({'saved': created, 'message': message, 'count': request.user.wishlist.count()})
    messages.success(request, message)
    return redirect_next(request, product.get_absolute_url())


@login_required
@require_POST
def review_create(request, slug):
    product = get_object_or_404(Product.objects.available(), slug=slug)
    if product.reviews.filter(user=request.user).exists():
        messages.info(request, 'You have already reviewed this product.')
        return redirect(product)
    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.product = product
        review.user = request.user
        review.verified_purchase = request.user.orders.filter(
            items__product=product, status__in=['paid', 'shipped', 'out_for_delivery', 'delivered'],
        ).exists()
        review.save()
        product.refresh_rating()
        messages.success(request, 'Thanks for your review!')
    else:
        messages.error(request, 'Please choose a star rating and add a title.')
    return redirect(product.get_absolute_url() + '#reviews')


def credits(request):
    images = ProductImage.objects.exclude(source_url='').select_related('product').order_by('product__name', 'position')
    return render(request, 'catalog/credits.html', {'images': images})
