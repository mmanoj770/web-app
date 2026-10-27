import random
from datetime import timedelta
from decimal import Decimal
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from catalog import commons
from catalog.models import Category, Product, Review

CATEGORIES = [
    # name, icon, tagline
    ('Smartphones', 'phone', 'Flagship cameras. All-day batteries.'),
    ('Laptops', 'laptop', 'Power for work, study and play.'),
    ('Headphones', 'headphones', 'Sound that moves you.'),
    ('Smartwatches', 'smartwatch', 'Your health, on your wrist.'),
    ('Tablets', 'tablet', 'Create, stream and learn anywhere.'),
    ('Accessories', 'mouse', 'Small things that make a big difference.'),
]

# Each product: brand, name, price, MRP, stock, featured, description, highlights, specs,
# and Wikimedia Commons photo titles (first one is the main image).
CATALOG = {
    'Smartphones': [
        ('Samsung', 'Galaxy S24 Ultra (12 GB / 256 GB)', 109999, 134999, 12, True,
         'Samsung\'s most powerful Galaxy with a built-in S Pen, a 200 MP camera and Galaxy AI features.',
         ['200 MP camera with 5x optical zoom', 'Built-in S Pen', 'Snapdragon 8 Gen 3 for Galaxy', 'Titanium frame'],
         {'Display': '6.8" QHD+ Dynamic AMOLED 2X, 120 Hz', 'Processor': 'Snapdragon 8 Gen 3', 'RAM': '12 GB',
          'Storage': '256 GB', 'Main camera': '200 MP + 50 MP 5x telephoto', 'Battery': '5000 mAh, 45 W'},
         ['Samsung Galaxy S24 (webtekno) 008.png', 'Samsung Galaxy S24 Ultra with retail box, front.jpg']),
        ('Apple', 'iPhone 15 (128 GB)', 69900, 79900, 10, True,
         'Dynamic Island, a 48 MP main camera and USB-C, in a colour-infused glass design.',
         ['Dynamic Island', '48 MP main camera with 2x telephoto', 'USB-C', 'A16 Bionic chip'],
         {'Display': '6.1" Super Retina XDR OLED', 'Processor': 'A16 Bionic', 'Storage': '128 GB',
          'Main camera': '48 MP', 'Battery': 'Up to 20 hours video playback'},
         ['Back of iPhone 15.jpg', 'Apple iPhone 15.jpeg']),
        ('Google', 'Pixel 8a (8 GB / 128 GB)', 39999, 52999, 9, False,
         'Google AI in a compact phone, with a brilliant camera and seven years of OS updates.',
         ['Google Tensor G3', '7 years of OS and security updates', '120 Hz Actua display', 'Magic Eraser and Best Take'],
         {'Display': '6.1" OLED, 120 Hz', 'Processor': 'Google Tensor G3', 'RAM': '8 GB', 'Storage': '128 GB',
          'Main camera': '64 MP', 'Battery': '4492 mAh'},
         ['Pixel 8a.jpg', 'Rear view of Pixel 8a.jpg']),
        ('Google', 'Pixel 8 (Rose, 128 GB)', 52999, 75999, 6, False,
         'The helpful Pixel with an upgraded camera, a bright display and Google AI built in.',
         ['Google Tensor G3', 'Pro-level 50 MP camera', '7 years of updates', 'Face and fingerprint unlock'],
         {'Display': '6.2" Actua OLED, 120 Hz', 'Processor': 'Google Tensor G3', 'RAM': '8 GB', 'Storage': '128 GB',
          'Main camera': '50 MP + 12 MP ultrawide', 'Battery': '4575 mAh'},
         ['Google Pixel 8 Rose rear.jpg', 'Google Pixel 8 Rose front.jpg']),
        ('OnePlus', 'Nord 5 (12 GB / 256 GB)', 31999, 34999, 20, False,
         'Flagship-grade speed and a huge battery that charges from 1% to 100% in about an hour.',
         ['Snapdragon 8s Gen 3', '6800 mAh battery, 80 W SUPERVOOC', '144 Hz AMOLED display', '50 MP Sony main camera'],
         {'Display': '6.83" AMOLED, 144 Hz', 'Processor': 'Snapdragon 8s Gen 3', 'RAM': '12 GB', 'Storage': '256 GB',
          'Main camera': '50 MP', 'Battery': '6800 mAh, 80 W charging'},
         ['OnePlus Nord 5 back.jpg', 'OnePlus Nord 5 front.jpg']),
        ('Xiaomi', 'Redmi Note 14 Pro+ 5G (8 GB / 256 GB)', 29999, 34999, 25, False,
         'A 200 MP camera, a curved AMOLED display and 90 W HyperCharge at a mid-range price.',
         ['200 MP main camera', '6200 mAh battery, 90 W charging', 'IP68 dust and water resistance', 'Curved AMOLED display'],
         {'Display': '6.67" curved AMOLED, 120 Hz', 'Processor': 'Snapdragon 7s Gen 3', 'RAM': '8 GB',
          'Storage': '256 GB', 'Main camera': '200 MP', 'Battery': '6200 mAh, 90 W charging'},
         ['Redmi Note 14 ProPlus.jpg']),
    ],
    'Laptops': [
        ('Apple', 'MacBook Air 13" (M2, 16 GB / 256 GB)', 99900, 114900, 5, True,
         'Strikingly thin and fanless, with the M2 chip and up to 18 hours of battery life.',
         ['Apple M2 chip', 'Up to 18 hours battery', '13.6" Liquid Retina display', 'MagSafe charging'],
         {'Processor': 'Apple M2 (8-core CPU, 8-core GPU)', 'RAM': '16 GB unified memory', 'Storage': '256 GB SSD',
          'Display': '13.6" Liquid Retina', 'Battery': 'Up to 18 hours', 'Weight': '1.24 kg'},
         ['M2 Macbook Air Midnight model - 1.jpg', 'M2 Macbook Air Midnight model - 2.jpg']),
        ('Lenovo', 'IdeaPad Flex 5 14" (Ryzen 5)', 54990, 74890, 14, False,
         'A 2-in-1 convertible that flips from laptop to tablet, ideal for students and work from home.',
         ['360° convertible touchscreen', '16 GB RAM · 512 GB SSD', 'Backlit keyboard', 'Up to 10 hours battery'],
         {'Processor': 'AMD Ryzen 5 7530U', 'RAM': '16 GB', 'Storage': '512 GB SSD',
          'Display': '14" WUXGA touch', 'Battery': 'Up to 10 hours', 'Weight': '1.55 kg'},
         ['Lenovo IdeaPad Flex14 laptop.jpg', 'Lenovo IdeaPad Flex14 laptop (Leftside).jpg']),
        ('HP', 'Pavilion 14 (Core i5)', 61990, 75000, 9, False,
         'A compact everyday laptop with a backlit keyboard and fast charging.',
         ['Intel Core i5 13th gen', '16 GB RAM · 512 GB SSD', 'Fast charge: 50% in 45 minutes', 'Backlit keyboard'],
         {'Processor': 'Intel Core i5-1335U', 'RAM': '16 GB', 'Storage': '512 GB SSD',
          'Display': '14" FHD IPS', 'Battery': 'Up to 8 hours', 'Weight': '1.41 kg'},
         ['HP Pavilion laptop.jpg']),
        ('ASUS', 'TUF Gaming F15 (RTX 4050)', 78990, 104990, 6, False,
         'A military-grade gaming laptop with a 144 Hz display and dedicated NVIDIA graphics.',
         ['NVIDIA GeForce RTX 4050', '144 Hz FHD display', 'MIL-STD-810H durability', 'RGB backlit keyboard'],
         {'Processor': 'Intel Core i5-12500H', 'RAM': '16 GB', 'Storage': '512 GB SSD', 'Graphics': 'RTX 4050 6 GB',
          'Display': '15.6" FHD, 144 Hz', 'Weight': '2.2 kg'},
         ['ASUS TUF Gaming 5 Pro Laptop.jpg']),
        ('Dell', 'XPS 13 (Core Ultra 7)', 124990, 149990, 4, False,
         'A precision-machined ultraportable with an edge-to-edge InfinityEdge display.',
         ['Intel Core Ultra 7', 'InfinityEdge display', 'Machined aluminium chassis', 'Just 1.19 kg'],
         {'Processor': 'Intel Core Ultra 7 155H', 'RAM': '16 GB LPDDR5x', 'Storage': '512 GB SSD',
          'Display': '13.4" FHD+', 'Battery': 'Up to 12 hours', 'Weight': '1.19 kg'},
         ['Dell XPS 13 9350.jpg']),
    ],
    'Headphones': [
        ('Apple', 'AirPods Pro (2nd generation, USB-C)', 22900, 24900, 15, True,
         'Up to 2x more Active Noise Cancellation, Adaptive Audio and Personalised Spatial Audio.',
         ['Active Noise Cancellation', 'Adaptive Audio and Transparency mode', 'Up to 6 hours listening (30 with case)',
          'IP54 dust, sweat and water resistant'],
         {'Type': 'In-ear, wireless', 'Noise cancelling': 'Yes, adaptive', 'Battery': '6 hours (30 with case)',
          'Charging': 'USB-C, MagSafe', 'Water resistance': 'IP54'},
         ['AirPods Pro (2nd generation).jpg']),
        ('Bose', 'QuietComfort Ultra Earbuds', 25900, 29900, 4, True,
         'World-class noise cancellation with immersive spatial audio in a secure, comfortable fit.',
         ['World-class noise cancelling', 'Immersive Audio', 'CustomTune sound calibration', 'IPX4 water resistant'],
         {'Type': 'In-ear, wireless', 'Noise cancelling': 'Yes', 'Battery': '6 hours (24 with case)',
          'Water resistance': 'IPX4'},
         ['Bose QuietComfort Ultra Earbuds - 2.jpg', 'Bose QuietComfort Ultra Earbuds - 1.jpg']),
        ('Sony', 'WH-1000XM3 Wireless Noise Cancelling', 19990, 29990, 8, False,
         'Industry-leading noise cancellation with 30-hour battery life and touch controls.',
         ['Industry-leading noise cancelling', '30 hours battery', 'Quick charge: 5 hours in 10 minutes', 'Touch controls'],
         {'Type': 'Over-ear, wireless', 'Noise cancelling': 'Yes', 'Battery': '30 hours', 'Weight': '255 g'},
         ['Sony-WH-1000XM3-kabellose-Bluetooth-Noise-Cancelling-Kopfhoerer.3.jpg',
          'Sony-WH-1000XM3-kabellose-Bluetooth-Noise-Cancelling-Kopfhoerer.jpg']),
        ('Apple', 'AirPods Max', 54900, 59900, 3, False,
         'High-fidelity over-ear headphones with computational audio and a knit-mesh canopy.',
         ['High-fidelity audio', 'Active Noise Cancellation', 'Spatial audio with head tracking', '20 hours battery'],
         {'Type': 'Over-ear, wireless', 'Noise cancelling': 'Yes', 'Battery': '20 hours', 'Weight': '385 g'},
         ['Apple AirPods Max.jpg', 'Apple AirPods Max 2.jpg']),
        ('Samsung', 'Galaxy Buds2 Pro', 9999, 17999, 18, False,
         'Hi-Fi 24-bit audio and intelligent ANC in an ergonomic, compact design.',
         ['24-bit Hi-Fi audio', 'Intelligent ANC', '360 Audio', 'IPX7 water resistant'],
         {'Type': 'In-ear, wireless', 'Noise cancelling': 'Yes', 'Battery': '5 hours (18 with case)',
          'Water resistance': 'IPX7'},
         ['Samsung Galaxy Buds2 Pro (Graphite).jpg', 'Samsung Galaxy Buds2 Pro (Graphite) (2).jpg']),
        ('JBL', 'Live 650BTNC', 7999, 13999, 22, False,
         'Affordable over-ear headphones with active noise cancelling and JBL Signature Sound.',
         ['Active noise cancelling', 'JBL Signature Sound', '20 hours with ANC', 'Voice assistant built in'],
         {'Type': 'Over-ear, wireless', 'Noise cancelling': 'Yes', 'Battery': '20 hours (ANC on)', 'Weight': '260 g'},
         ['JBL LIVE 650 BTNC (Over-Ear Noise Cancelling Headphone). (51127342181).jpg']),
        ('JBL', 'Endurance Peak 3', 4999, 7999, 30, False,
         'Sport earbuds with secure ear hooks, IP68 protection and up to 50 hours of play.',
         ['IP68 dust and waterproof', 'Up to 50 hours playtime', 'Secure Powerhook design', 'Ambient Aware'],
         {'Type': 'In-ear sport, wireless', 'Noise cancelling': 'No', 'Battery': '10 hours (50 with case)',
          'Water resistance': 'IP68'},
         ['JBL Endurance Peak 3 - 1.jpg', 'JBL Endurance Peak 3 - 3.jpg']),
        ('Sennheiser', 'HD 25 Studio Headphones', 12990, 14990, 0, False,
         'The legendary closed-back headphones trusted by DJs and broadcasters for decades.',
         ['Closed-back, high isolation', 'Rotatable ear cup', 'Split headband', 'Replaceable parts'],
         {'Type': 'On-ear, wired', 'Noise cancelling': 'Passive isolation', 'Impedance': '70 Ω', 'Weight': '140 g'},
         ['Sennheiser hd-25 headphones.jpg']),
    ],
    'Smartwatches': [
        ('Apple', 'Watch SE (2nd gen, GPS, 40 mm)', 24900, 29900, 6, False,
         'All the essentials to stay active, connected and safe, with Crash Detection.',
         ['Heart rate and sleep tracking', 'Crash and fall detection', 'Swimproof (50 m)', 'Works with iPhone'],
         {'Display': '40 mm Retina OLED', 'Battery': 'Up to 18 hours', 'Water resistance': '50 m', 'GPS': 'Yes'},
         ['Watch SE (2nd generation).jpg', 'Apple Watch SE 2 (GPS + Cellular, 40mm, Midnight) with Anchor Blue Sport Loop.jpg']),
        ('Samsung', 'Galaxy Watch6 (40 mm)', 18999, 29999, 9, True,
         'A larger, brighter display with personalised sleep coaching and body composition insights.',
         ['Sleep coaching', 'Body composition (BIA) sensor', 'Sapphire crystal glass', 'Wear OS with Google apps'],
         {'Display': '1.3" Super AMOLED', 'Battery': 'Up to 40 hours', 'Water resistance': '5 ATM + IP68', 'GPS': 'Yes'},
         ['Samsung Galaxy Watch 6 3.jpg', 'Samsung Galaxy Watch 6.jpg']),
        ('Samsung', 'Galaxy Watch6 Classic (43 mm)', 26999, 36999, 5, False,
         'The iconic rotating bezel returns, in a classic stainless-steel design.',
         ['Rotating bezel', 'Stainless steel case', 'ECG and blood pressure', 'Wear OS with Google apps'],
         {'Display': '1.3" Super AMOLED', 'Battery': 'Up to 40 hours', 'Water resistance': '5 ATM + IP68', 'GPS': 'Yes'},
         ['Samsung Galaxy Watch6 Classic 43mm.jpg']),
        ('Huawei', 'Watch Fit 2', 12999, 18999, 11, False,
         'A slim smart band-style watch with a large AMOLED screen and up to 10 days of battery.',
         ['1.74" AMOLED display', 'Up to 10 days battery', '97 workout modes', 'Bluetooth calling'],
         {'Display': '1.74" AMOLED', 'Battery': 'Up to 10 days', 'Water resistance': '5 ATM', 'GPS': 'Built-in'},
         ['Huawei Smartwatch Fit 2.jpg']),
    ],
    'Tablets': [
        ('Apple', 'iPad (10th generation, Wi-Fi, 64 GB)', 32900, 34900, 7, True,
         'The colourful, all-screen iPad for study, streaming and notes. Keyboard sold separately.',
         ['10.9" Liquid Retina display', 'A14 Bionic chip', 'Landscape 12 MP front camera', 'USB-C'],
         {'Display': '10.9" Liquid Retina', 'Processor': 'A14 Bionic', 'Storage': '64 GB',
          'Pencil support': 'Apple Pencil (USB-C)', 'Battery': 'Up to 10 hours'},
         ['IPad 10th Generation 2024.jpg', 'About iPad (10th generation).jpg']),
        ('Samsung', 'Galaxy Tab S9 (Wi-Fi, 128 GB)', 64999, 72999, 4, False,
         'A premium Dynamic AMOLED tablet with IP68 water resistance and the S Pen included.',
         ['11" Dynamic AMOLED 2X', 'S Pen included', 'IP68 water resistance', 'Snapdragon 8 Gen 2'],
         {'Display': '11" Dynamic AMOLED 2X, 120 Hz', 'Processor': 'Snapdragon 8 Gen 2', 'Storage': '128 GB',
          'Pencil support': 'S Pen included', 'Battery': '8400 mAh'},
         ['20230729 삼성 갤럭시 탭 S9.jpg', 'Samsung Galaxy Tab S9.png']),
        ('Lenovo', 'Tab M10 FHD Plus', 13999, 22000, 15, False,
         'An affordable family tablet for video calls, streaming and online classes.',
         ['10.6" 2K display', 'Quad speakers with Dolby Atmos', 'Kids mode', 'Up to 10 hours video'],
         {'Display': '10.6" 2K IPS', 'Processor': 'MediaTek Helio G80', 'Storage': '64 GB',
          'Pencil support': 'Lenovo Tab Pen', 'Battery': '7700 mAh'},
         ['Lenovo Tab M10 FHD Plus (2026).jpg']),
    ],
    'Accessories': [
        ('Logitech', 'MX Master 3S Wireless Mouse', 8995, 10995, 14, False,
         'An iconic performance mouse with quiet clicks and an 8K DPI sensor that tracks on glass.',
         ['Quiet clicks', '8000 DPI, tracks on glass', 'MagSpeed electromagnetic scrolling', 'Up to 70 days per charge'],
         {'Connectivity': 'Bluetooth / Logi Bolt receiver', 'Battery': 'Up to 70 days', 'DPI': '8000'},
         ['Logitech MX Master 3S HS12.jpg', 'Logitech MX Master 3S HS02.jpg', 'Logitech MX Master 3S HS13.jpg']),
        ('SanDisk', 'Extreme Portable SSD 1 TB', 7999, 15999, 3, False,
         'A rugged pocket-sized SSD with up to 1050 MB/s reads, drop and water protection.',
         ['Up to 1050 MB/s read speed', '3 m drop protection', 'IP65 water and dust resistance', 'USB-C'],
         {'Capacity': '1 TB', 'Speed': 'Up to 1050 MB/s', 'Interface': 'USB-C 3.2 Gen 2'},
         ['SanDisk Extreme Portable SSD 1 TB - front view.jpg',
          'SanDisk Extreme Portable SSD 1 TB - front view with cable.jpg']),
        ('Anker', 'PowerPort 40 W 5-Port USB Charger', 2299, 2999, 35, False,
         'Charge five devices at once from a single compact desktop charger.',
         ['5 USB ports', '40 W total output', 'PowerIQ fast charging', 'MultiProtect safety system'],
         {'Output': '40 W', 'Ports': '5x USB-A'},
         ['Anker-PowerPort-40W-5-Port-USB-Ladegeraet.jpg', 'Anker-PowerPort-40W-5-Port-USB-Ladegeraet.2.jpg']),
    ],
}

USERS = [
    # username, password, role, first, last, superuser
    ('admin', 'Admin@12345', 'admin', 'Asha', 'Admin', True),
    ('agent1', 'Agent@12345', 'agent', 'Ravi', 'Kumar', False),
    ('agent2', 'Agent@12345', 'agent', 'Priya', 'Nair', False),
    ('customer', 'Customer@12345', 'customer', 'Arjun', 'Mehta', False),
]

# Demo reviewers and review texts, so ratings and reviews have something to show.
REVIEWERS = [('demo_neha', 'Neha'), ('demo_rahul', 'Rahul'), ('demo_sana', 'Sana'), ('demo_vikram', 'Vikram')]
REVIEW_TEXTS = {
    5: [('Absolutely love it', 'Exactly as described and delivery was quick. Build quality feels premium.'),
        ('Worth every rupee', 'Works perfectly and the packaging was great. Highly recommended.'),
        ('Excellent', 'Using it daily for a few weeks now. No complaints at all.')],
    4: [('Very good', 'Does everything I need. A couple of minor nitpicks but great overall.'),
        ('Good value', 'Solid product for the price. Setup was easy.')],
    3: [('Decent', "It's okay for the price. A few things could be better.")],
}


class Command(BaseCommand):
    help = 'Load the demo catalog, product photos, demo reviews and users (safe to run more than once).'

    def add_arguments(self, parser):
        parser.add_argument('--no-users', action='store_true', help='Skip demo users.')
        parser.add_argument('--no-images', action='store_true', help='Skip downloading product photos.')
        parser.add_argument('--refresh-images', action='store_true', help='Re-download photos that already exist.')

    def handle(self, *args, **options):
        products = self.load_catalog()
        if not options['no_users']:
            self.load_users()
            self.load_reviews(products)
            self.load_demo_orders()
        if not options['no_images']:
            self.load_images(products, refresh=options['refresh_images'])

    @transaction.atomic
    def load_catalog(self):
        products = []
        for position, (name, icon, tagline) in enumerate(CATEGORIES):
            category, _ = Category.objects.update_or_create(
                slug=slugify(name), defaults={'name': name, 'icon': icon, 'tagline': tagline, 'position': position},
            )
            for brand, model, price, mrp, stock, featured, description, highlights, specs, photos in CATALOG[name]:
                full_name = f'{brand} {model}'
                product, _ = Product.objects.update_or_create(
                    slug=slugify(full_name)[:200],
                    defaults={
                        'category': category, 'name': full_name, 'brand': brand, 'price': Decimal(price),
                        'mrp': Decimal(mrp), 'stock': stock, 'is_featured': featured, 'description': description,
                        'highlights': highlights, 'specs': specs, 'is_active': True,
                    },
                )
                products.append((product, photos))
        self.stdout.write(self.style.SUCCESS(f'Loaded {len(CATEGORIES)} categories and {len(products)} products.'))
        return products

    def load_users(self):
        User = get_user_model()
        for username, password, role, first, last, superuser in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'email': f'{username}@mj.local', 'role': role, 'first_name': first,
                          'last_name': last, 'is_superuser': superuser},
            )
            if created:
                user.set_password(password)
                if role == 'customer':
                    user.phone, user.address_line = '9876543210', '12 MG Road, Indiranagar'
                    user.city, user.postal_code = 'Bengaluru', '560038'
                user.save()
                self.stdout.write(f'  created {role:<8} {username} / {password}')
        self.stdout.write(self.style.WARNING('Demo passwords are for local development only.'))

    @transaction.atomic
    def load_reviews(self, products):
        User = get_user_model()
        reviewers = []
        for username, first in REVIEWERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={'email': f'{username}@mj.local', 'first_name': first},
            )
            if created:
                user.set_unusable_password()
                user.save()
            reviewers.append(user)
        for product, _photos in products:
            rng = random.Random(product.slug)  # Same reviews on every run.
            for user in rng.sample(reviewers, rng.randint(2, 4)):
                rating = rng.choice([5, 5, 5, 4, 4, 3])
                title, body = rng.choice(REVIEW_TEXTS[rating])
                Review.objects.get_or_create(product=product, user=user,
                                             defaults={'rating': rating, 'title': title, 'body': body})
            product.refresh_rating()
        self.stdout.write(f'  demo reviews for {len(products)} products')

    @transaction.atomic
    def load_demo_orders(self):
        """Give the demo customer a delivered order, an order in transit and an open ticket."""
        from orders.models import Order, OrderEvent, OrderItem, Payment
        from support import services as support_services
        from support.models import Ticket

        customer = get_user_model().objects.filter(username='customer').first()
        if customer is None or customer.orders.exists():
            return
        now = timezone.now()
        address = {'full_name': 'Arjun Mehta', 'phone': '9876543210', 'address_line': '12 MG Road, Indiranagar',
                   'city': 'Bengaluru', 'postal_code': '560038'}
        plans = [
            # product slug, days ago, final status, carrier, tracking number
            ('apple-airpods-pro-2nd-generation-usb-c', 12, Order.Status.DELIVERED, 'Blue Dart', 'BD58213490IN'),
            ('samsung-galaxy-watch6-40-mm', 2, Order.Status.SHIPPED, 'Delhivery', 'DL7742019365'),
        ]
        steps = [Order.Status.PAID, Order.Status.SHIPPED, Order.Status.OUT_FOR_DELIVERY, Order.Status.DELIVERED]
        orders = []
        for slug, days_ago, final, carrier, tracking in plans:
            product = Product.objects.filter(slug=slug).first()
            if product is None:
                continue
            placed = now - timedelta(days=days_ago)
            order = Order.objects.create(user=customer, total=product.price, status=final, carrier=carrier,
                                         tracking_number=tracking, **address)
            Order.objects.filter(pk=order.pk).update(created_at=placed)
            OrderItem.objects.create(order=order, product=product, product_name=product.name,
                                     unit_price=product.price, quantity=1)
            Payment.objects.create(order=order, amount=product.price, method=Payment.Method.UPI,
                                   status=Payment.Status.SUCCESS, reference=f'PAY-DEMO{order.pk:04d}',
                                   upi_id='arjun@okbank')
            events = [(Order.Status.PENDING, 'Order placed.')] + [
                (status, f'Shipped with {carrier}.' if status == Order.Status.SHIPPED else '')
                for status in steps[:steps.index(final) + 1]
            ]
            for hours, (status, note) in enumerate(events):
                event = OrderEvent.objects.create(order=order, status=status, note=note)
                OrderEvent.objects.filter(pk=event.pk).update(created_at=placed + timedelta(hours=hours * 20))
            orders.append(order)

        if len(orders) == 2:
            support_services.create_ticket(
                customer, Ticket.Category.MISSING_DELIVERY, 'Watch delivery is taking longer than expected',
                'Tracking has not updated since it was shipped. Can you check with the courier?', order=orders[1],
            )
        self.stdout.write(f'  demo orders for customer: {", ".join(o.number for o in orders)}')

    def load_images(self, products, refresh=False):
        todo = [(p, photos) for p, photos in products if refresh or not p.images.exists()]
        if not todo:
            self.stdout.write('Product photos already downloaded (use --refresh-images to fetch again).')
            return
        titles = sorted({title for _p, photos in todo for title in photos})
        self.stdout.write(f'Downloading {len(titles)} photos from Wikimedia Commons...')
        try:
            found = commons.lookup(titles)
        except (URLError, TimeoutError, OSError) as exc:
            self.stderr.write(self.style.ERROR(f'Could not reach Wikimedia Commons ({exc}); skipping photos.'))
            return
        saved = 0
        for product, photos in todo:
            if refresh:
                for image in product.images.all():
                    image.image.delete(save=False)
                    image.thumbnail.delete(save=False)
                    image.delete()
            for position, title in enumerate(photos):
                photo = found.get(title)
                if photo is None:
                    self.stderr.write(f'  not found on Commons: {title}')
                    continue
                try:
                    commons.attach(product, photo, position)
                    saved += 1
                except (URLError, TimeoutError, OSError) as exc:
                    self.stderr.write(f'  failed {title}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Saved {saved} product photos with attribution.'))
