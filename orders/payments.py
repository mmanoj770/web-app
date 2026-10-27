"""Simulated payment gateway for cards and UPI.

This stands in for a real provider (Stripe, Razorpay, ...) so checkout can be
exercised end to end without external accounts. Swap `charge_card` and
`charge_upi` for a real integration before taking actual payments, and never
store full card numbers.

Test cards:
    4242 4242 4242 4242  -> success
    4000 0000 0000 0002  -> declined
    4000 0000 0000 9995  -> insufficient funds
Test UPI IDs:
    anything@okbank      -> success
    fail@upi             -> declined
"""
import re
import uuid
from dataclasses import dataclass

CARD_DECLINES = {
    '4000000000000002': 'Your card was declined.',
    '4000000000009995': 'Insufficient funds.',
}
UPI_DECLINES = {'fail@upi': 'The payment request was declined in your UPI app.'}
UPI_RE = re.compile(r'^[\w.\-]{2,}@[a-zA-Z]{2,}$')


@dataclass
class ChargeResult:
    success: bool
    reference: str = ''
    failure_reason: str = ''


def _reference():
    return f'PAY-{uuid.uuid4().hex[:12].upper()}'


def luhn_valid(number):
    digits = [int(d) for d in number]
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def normalize_card(number):
    return ''.join(ch for ch in number if ch.isdigit())


def charge_card(amount, card_number):
    card = normalize_card(card_number)
    if not 12 <= len(card) <= 19 or not luhn_valid(card):
        return ChargeResult(False, failure_reason='Invalid card number.')
    if card in CARD_DECLINES:
        return ChargeResult(False, failure_reason=CARD_DECLINES[card])
    return ChargeResult(True, reference=_reference())


def charge_upi(amount, upi_id):
    upi_id = upi_id.strip().lower()
    if not UPI_RE.match(upi_id):
        return ChargeResult(False, failure_reason='Invalid UPI ID.')
    if upi_id in UPI_DECLINES:
        return ChargeResult(False, failure_reason=UPI_DECLINES[upi_id])
    return ChargeResult(True, reference=_reference())


# Kept for callers that only deal with cards.
charge = charge_card
