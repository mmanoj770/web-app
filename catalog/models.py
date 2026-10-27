from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count
from django.urls import reverse


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    tagline = models.CharField(max_length=120, blank=True)
    # Bootstrap Icons name, e.g. "laptop".
    icon = models.CharField(max_length=40, default='box-seam')
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('catalog:product_list') + f'?category={self.slug}'

    @property
    def cover_image(self):
        image = ProductImage.objects.filter(product__category=self, product__is_active=True,
                                            product__is_featured=True).order_by('product__pk', 'position').first()
        return image or ProductImage.objects.filter(product__category=self).order_by('position').first()


class ProductQuerySet(models.QuerySet):
    def available(self):
        return self.filter(is_active=True)

    def with_images(self):
        return self.prefetch_related('images')


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    brand = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # Maximum retail price; the difference to `price` is shown as a discount.
    mrp = models.DecimalField('MRP', max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    # Short selling points shown as bullets, e.g. ["16 GB RAM", "All-day battery"].
    highlights = models.JSONField(default=list, blank=True)
    # Free-form key/value specs, e.g. {"RAM": "16 GB"}. The AI assistant reads these to compare products.
    specs = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    # Denormalised from reviews so listings can sort and filter by rating cheaply.
    rating_avg = models.DecimalField(max_digits=2, decimal_places=1, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['is_active', 'category'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('catalog:product_detail', args=[self.slug])

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def list_price(self):
        return self.mrp if self.mrp and self.mrp > self.price else self.price

    @property
    def discount_percent(self):
        if not self.mrp or self.mrp <= self.price:
            return 0
        return int((self.mrp - self.price) * 100 / self.mrp)

    @property
    def savings(self):
        return self.list_price - self.price

    @property
    def primary_image(self):
        # Uses the prefetch cache when the queryset called with_images().
        images = list(self.images.all())
        return images[0] if images else None

    def refresh_rating(self):
        stats = self.reviews.aggregate(avg=Avg('rating'), count=Count('id'))
        self.rating_avg = Decimal(str(round(stats['avg'] or 0, 1)))
        self.rating_count = stats['count']
        self.save(update_fields=['rating_avg', 'rating_count'])


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/')
    thumbnail = models.ImageField(upload_to='products/thumbs/', blank=True)
    alt = models.CharField(max_length=200, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    # Attribution for openly licensed photos (e.g. from Wikimedia Commons).
    author = models.CharField(max_length=255, blank=True)
    license = models.CharField(max_length=100, blank=True)
    license_url = models.URLField(blank=True)
    source_url = models.URLField(blank=True)

    class Meta:
        ordering = ['position', 'pk']

    def __str__(self):
        return f'{self.product} image {self.position}'

    @property
    def thumb_url(self):
        return (self.thumbnail or self.image).url

    @property
    def needs_credit(self):
        return bool(self.source_url)


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    verified_purchase = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['product', 'user'], name='one_review_per_user')]

    def __str__(self):
        return f'{self.rating}★ {self.product} by {self.user}'


class WishlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['user', 'product'], name='unique_wishlist_item')]
