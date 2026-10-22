from .models import ShopSettings


def shop(request):
    """Expose shop settings to every template as {{ shop }}."""
    return {'shop': ShopSettings.load()}
