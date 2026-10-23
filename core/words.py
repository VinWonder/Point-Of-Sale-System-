"""Amounts in words for quotations and invoices: 'Kenya Shillings One Thousand ... Only'."""
from decimal import ROUND_HALF_UP, Decimal

ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
        'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
SCALES = [(10 ** 9, 'Billion'), (10 ** 6, 'Million'), (1000, 'Thousand')]


def _below_thousand(n):
    words = []
    if n >= 100:
        words += [ONES[n // 100], 'Hundred']
        n %= 100
        if n:
            words.append('and')
    if n >= 20:
        words.append(TENS[n // 10] + (f'-{ONES[n % 10]}' if n % 10 else ''))
    elif n:
        words.append(ONES[n])
    return ' '.join(words)


def number_to_words(n):
    if n == 0:
        return 'Zero'
    parts = []
    for value, name in SCALES:
        if n >= value:
            parts.append(f'{_below_thousand(n // value)} {name}')
            n %= value
    if n:
        # British style: "One Thousand and Five"
        if parts and n < 100:
            parts.append('and')
        parts.append(_below_thousand(n))
    return ' '.join(parts)


def amount_in_words(amount, currency='Kenya Shillings'):
    amount = Decimal(amount or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    shillings = int(amount)
    cents = int((amount - shillings) * 100)
    text = f'{currency} {number_to_words(shillings)}'
    if cents:
        text += f' and {number_to_words(cents)} Cents'
    return text + ' Only'
