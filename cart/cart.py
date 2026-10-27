from decimal import Decimal

from catalog.models import Product

SESSION_KEY = 'cart'


class Cart:
    """Shopping cart stored in the session as {product_id: quantity}."""

    def __init__(self, request):
        self.session = request.session
        self.items = self.session.setdefault(SESSION_KEY, {})

    def _save(self):
        self.session.modified = True

    def add(self, product, quantity=1):
        key = str(product.pk)
        self.set(product, self.items.get(key, 0) + quantity)

    def set(self, product, quantity):
        """Set an item's quantity, capped at the available stock."""
        key = str(product.pk)
        quantity = min(int(quantity), product.stock)
        if quantity > 0:
            self.items[key] = quantity
        else:
            self.items.pop(key, None)
        self._save()

    def remove(self, product):
        self.items.pop(str(product.pk), None)
        self._save()

    def clear(self):
        self.items.clear()
        self._save()

    def lines(self):
        products = (Product.objects.available().select_related('category').with_images()
                    .filter(pk__in=self.items.keys()))
        # Drop products that were deactivated or deleted since they were added,
        # otherwise checkout would keep failing on an item the customer can't see.
        found = {str(p.pk) for p in products}
        stale = [key for key in self.items if key not in found]
        for key in stale:
            del self.items[key]
        if stale:
            self._save()
        lines = []
        for product in products:
            quantity = self.items[str(product.pk)]
            lines.append({
                'product': product,
                'quantity': quantity,
                'line_total': product.price * quantity,
                'line_mrp': product.list_price * quantity,
            })
        return lines

    def summary(self, lines=None):
        """Price breakdown for the cart and checkout pages."""
        lines = self.lines() if lines is None else lines
        total = sum((line['line_total'] for line in lines), Decimal('0'))
        mrp = sum((line['line_mrp'] for line in lines), Decimal('0'))
        return {
            'count': sum(line['quantity'] for line in lines),
            'mrp': mrp,
            'discount': mrp - total,
            'delivery': Decimal('0'),
            'total': total,
        }

    @property
    def total(self):
        return self.summary()['total']

    def __len__(self):
        return sum(self.items.values())
