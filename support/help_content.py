"""Starting help-center content, loaded into the FAQ and ErrorCode tables by a data migration.

Edit the live content in the Django admin; this file only seeds new databases.
"""

# (category, question, answer, keywords, ticket_category)
FAQS = [
    ('orders', 'When will my order arrive?',
     'Orders are delivered in 3-5 business days in metro cities and 5-8 business days elsewhere, and delivery '
     'is free on every order. You can follow every step from My orders.',
     'delivery time how long shipping days arrive eta', ''),
    ('orders', 'How do I track my order?',
     'Open My orders and select the order. You will see each step from Ordered to Delivered, plus the courier '
     'and tracking number once it ships. You can also ask the assistant "where is my order?".',
     'track tracking status where courier awb', ''),
    ('orders', 'Can I change my delivery address?',
     'You can cancel an unpaid order and place it again with the new address. For paid orders, raise a ticket '
     'with the new address and we will try to update it before it ships.',
     'change update wrong address location', 'other'),
    ('orders', 'Can I cancel my order?',
     'Orders awaiting payment can be cancelled from My orders. Once an order is paid or shipped, raise a ticket '
     'and our team will help.',
     'cancel cancellation stop order', 'other'),
    ('orders', 'My order shows delivered but I have not received it',
     'Check with neighbours or your building security first. If it is still missing, raise a "Missing / late '
     'delivery" ticket and we will investigate with the courier.',
     'delivered not received missing lost package', 'missing_delivery'),
    ('payments', 'Which payment methods do you accept?',
     'UPI (Google Pay, PhonePe, Paytm and any UPI app) and all major credit and debit cards. Cash on delivery '
     'is not available yet.',
     'payment methods upi card credit debit cod cash', ''),
    ('payments', 'Money was deducted but the payment failed',
     'Failed payments are usually reversed by your bank automatically within 5-7 business days. If it has been '
     'longer, raise a "Payment failure" ticket with the order number.',
     'deducted debited charged failed payment money reversed', 'payment_failure'),
    ('payments', 'How long do refunds take?',
     'Approved refunds go back to your original payment method within 5-7 business days.',
     'refund time how long money back days', ''),
    ('payments', 'Is it safe to pay on MJ?',
     'Yes. Payments are processed by the payment gateway over an encrypted connection, and we never store your '
     'full card number or UPI PIN.',
     'safe secure security card details pin', ''),
    ('returns', 'What is the return policy?',
     'You can return damaged, defective or wrong items within 7 days of delivery. Raise a "Return or refund" '
     'ticket with your order number to start a return.',
     'return policy exchange replace days', 'refund'),
    ('returns', 'My product arrived damaged',
     'Sorry about that! Raise a "Damaged or wrong product" ticket and attach photos of the item and the box so '
     'we can arrange a replacement quickly.',
     'damaged broken defective cracked wrong item not working', 'damaged_product'),
    ('returns', 'Do products come with a warranty?',
     'Yes. Every product carries the manufacturer\'s warranty, usually 1 year. Keep your order invoice from My '
     'orders for warranty claims at the brand\'s service centre.',
     'warranty guarantee service centre repair invoice', ''),
    ('account', 'How do I contact customer support?',
     'Raise a ticket from the Help page or ask the assistant. You get a ticket ID, email updates and can reply '
     'on the ticket page. We reply within 4 hours for payment and delivery issues and 24 hours otherwise.',
     'contact support agent human customer care help call', 'other'),
    ('account', 'What does an error code like PAY-001 mean?',
     'Error codes tell you exactly what went wrong. Look the code up on the Error codes page or ask the '
     'assistant, for example "what does PAY-001 mean?", to see what happened and how to fix it.',
     'error code meaning failed message', ''),
]

# (code, title, area, http_status, meaning, resolution, ticket_category)
ERROR_CODES = [
    ('PAY-001', 'Card declined', 'payments', 402,
     'Your bank declined the card payment.',
     'Try another card or pay by UPI. If your bank says the payment went through, raise a payment ticket.',
     'payment_failure'),
    ('PAY-002', 'Insufficient funds', 'payments', 402,
     'The card does not have enough available balance or limit for this order.',
     'Use another card or UPI, or ask your bank to raise the limit, then retry from My orders.', ''),
    ('PAY-003', 'Invalid card number', 'payments', 400,
     'The card number failed validation, usually because of a typo.',
     'Check the 16-digit number on your card and enter it again.', ''),
    ('PAY-004', 'UPI request declined', 'payments', 402,
     'The payment request was declined or expired in your UPI app.',
     'Approve the request in your UPI app within 5 minutes, or try another UPI ID or a card.',
     'payment_failure'),
    ('PAY-005', 'Invalid UPI ID', 'payments', 400,
     'The UPI ID is not in the right format (for example name@okbank).',
     'Check your UPI ID in your UPI app and enter it again.', ''),
    ('ORD-001', 'Not enough stock', 'orders', 409,
     'Fewer units are left than the quantity in your bag.',
     'Reduce the quantity in your bag, or add the item to your wishlist to buy it when it is back.', ''),
    ('ORD-002', 'Item no longer available', 'orders', 410,
     'A product in your bag was removed from the store.',
     'Remove it from your bag and try the similar products on the product page.', ''),
    ('ORD-003', 'Bag is empty', 'orders', 400,
     'Checkout was opened with nothing in the bag.',
     'Add products to your bag and check out again.', ''),
    ('ORD-004', 'Order cannot be paid', 'orders', 409,
     'The order was already paid or was cancelled, so it cannot be paid again.',
     'Check the order status in My orders. If you were charged twice, raise a payment ticket.',
     'payment_failure'),
    ('WEB-400', 'Bad request', 'website', 400,
     'The request was missing information or had something in the wrong format, e.g. an invalid PIN code.',
     'Check what you entered and try again. If it keeps happening, refresh the page.', ''),
    ('WEB-401', 'Sign-in required', 'website', 401,
     'This needs you to be signed in, or your session has expired.',
     'Sign in and try again. You stay signed in for two weeks on the same device.', ''),
    ('WEB-403', 'Access denied', 'website', 403,
     'Your account does not have permission to open this page.',
     'Log in with the right account. Staff pages need an agent or admin account.', ''),
    ('WEB-404', 'Page not found', 'website', 404,
     'The page does not exist or has moved.',
     'Use search or the menu to find what you need, or ask the assistant.', ''),
    ('WEB-500', 'Something went wrong on our side', 'website', 500,
     'The server hit an unexpected error while loading the page. It has been logged for our team.',
     'Refresh the page in a minute. If it keeps happening, raise a ticket and mention what you were doing.',
     'other'),
    ('WEB-503', 'Service unavailable', 'website', 503,
     'A service the site depends on (such as the database) is temporarily unavailable or under maintenance.',
     'Wait a minute and try again. You can check the live status at /health/.', 'other'),
    ('AI-429', 'Too many messages', 'assistant', 429,
     'You sent more chat messages in a minute than the assistant allows.',
     'Wait a minute and send your message again.', ''),
]


def load(apps=None, only_missing=False):
    """Create the starting FAQs and error codes; existing ones are updated unless only_missing is set."""
    if apps is None:
        from .models import FAQ, ErrorCode
    else:
        FAQ = apps.get_model('support', 'FAQ')
        ErrorCode = apps.get_model('support', 'ErrorCode')
    save = 'get_or_create' if only_missing else 'update_or_create'
    for position, (category, question, answer, keywords, ticket_category) in enumerate(FAQS):
        getattr(FAQ.objects, save)(question=question, defaults={
            'category': category, 'answer': answer, 'keywords': keywords,
            'ticket_category': ticket_category, 'position': position,
        })
    for code, title, area, http_status, meaning, resolution, ticket_category in ERROR_CODES:
        getattr(ErrorCode.objects, save)(code=code, defaults={
            'title': title, 'area': area, 'http_status': http_status, 'meaning': meaning,
            'resolution': resolution, 'ticket_category': ticket_category,
        })
