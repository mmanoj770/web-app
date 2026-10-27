from django.contrib import admin

from .models import Category, Product, ProductImage, Review, WishlistItem


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'position')
    list_editable = ('position',)
    prepopulated_fields = {'slug': ('name',)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ('image', 'position', 'alt', 'author', 'license', 'source_url')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'brand', 'price', 'mrp', 'stock', 'rating_avg', 'is_featured', 'is_active')
    list_editable = ('price', 'mrp', 'stock', 'is_featured', 'is_active')
    list_filter = ('category', 'is_active', 'is_featured', 'brand')
    search_fields = ('name', 'brand', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('rating_avg', 'rating_count')
    inlines = [ProductImageInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'title', 'verified_purchase', 'created_at')
    list_filter = ('rating', 'verified_purchase')
    search_fields = ('product__name', 'user__username', 'title')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.product.refresh_rating()

    def delete_model(self, request, obj):
        product = obj.product
        super().delete_model(request, obj)
        product.refresh_rating()


admin.site.register(WishlistItem)
