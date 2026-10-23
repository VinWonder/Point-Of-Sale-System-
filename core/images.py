import base64
import io

from django.core.exceptions import ValidationError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SIDE = 400


def logo_to_data_uri(upload):
    """
    Validate an uploaded image, shrink it to at most 400px and re-encode it as
    PNG. Re-encoding through Pillow means only real pixels are stored — any
    script or metadata hidden in the upload is discarded.
    """
    from PIL import Image, UnidentifiedImageError

    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError('Logo is too large (max 2 MB).')
    try:
        image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ValidationError('Upload a PNG, JPG or WebP image.')
    if image.format not in ('PNG', 'JPEG', 'WEBP', 'GIF'):
        raise ValidationError('Upload a PNG, JPG or WebP image.')

    image = image.convert('RGBA')
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
