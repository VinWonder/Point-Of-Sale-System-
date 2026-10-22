import re

from django.conf import settings


class InvalidPhoneNumber(ValueError):
    pass


def normalize_phone(raw):
    """
    Accept the ways cashiers actually type Kenyan numbers and return the
    2547XXXXXXXX / 2541XXXXXXXX format Daraja requires.

        0712 345 678 -> 254712345678
        +254712345678 -> 254712345678
        712345678 -> 254712345678
    """
    digits = re.sub(r'\D', '', raw or '')
    if digits.startswith('254'):
        digits = digits[3:]
    elif digits.startswith('0'):
        digits = digits[1:]
    if len(digits) != 9 or digits[0] not in '17':
        raise InvalidPhoneNumber('Enter a valid Safaricom number, e.g. 0712 345 678.')
    return '254' + digits


def mpesa_is_configured():
    return bool(settings.MPESA_CONSUMER_KEY and settings.MPESA_CONSUMER_SECRET and settings.MPESA_PASSKEY)


def simulation_enabled():
    """
    Without Daraja credentials in DEBUG mode, STK pushes are simulated so the
    checkout flow can be demoed end-to-end on a laptop.
    """
    return settings.DEBUG and not mpesa_is_configured()
