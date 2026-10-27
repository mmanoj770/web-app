"""Download openly licensed product photos from Wikimedia Commons.

Every photo keeps its author, licence and source link so the store can show
the attribution that CC BY / CC BY-SA licences require.
"""
import html
import io
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.utils.html import strip_tags
from PIL import Image, ImageOps

API_URL = 'https://commons.wikimedia.org/w/api.php'
# Wikimedia asks API clients to identify themselves with a contact address or URL.
USER_AGENT = os.environ.get(
    'COMMONS_USER_AGENT', 'MJ-demo-store/1.0 (Django demo store; https://www.mediawiki.org/wiki/API:Etiquette)',
)
FULL_SIZE = 1200
THUMB_SIZE = 480


@dataclass
class CommonsPhoto:
    title: str
    url: str
    author: str
    license: str
    license_url: str
    source_url: str


def _get(url, timeout=60):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def lookup(titles):
    """Return {title: CommonsPhoto} for Commons file titles (without the "File:" prefix)."""
    photos = {}
    for start in range(0, len(titles), 40):
        batch = titles[start:start + 40]
        params = {
            'action': 'query', 'format': 'json', 'prop': 'imageinfo',
            'titles': '|'.join(f'File:{t}' for t in batch),
            'iiprop': 'url|extmetadata', 'iiurlwidth': FULL_SIZE,
        }
        data = json.loads(_get(f'{API_URL}?{urllib.parse.urlencode(params)}'))
        # The API may normalise titles (e.g. first letter upper-cased); map them back.
        renamed = {n['to']: n['from'] for n in data['query'].get('normalized', [])}
        for page in data['query']['pages'].values():
            if 'imageinfo' not in page:
                continue
            info = page['imageinfo'][0]
            meta = info.get('extmetadata', {})
            title = renamed.get(page['title'], page['title'])[len('File:'):]
            photos[title] = CommonsPhoto(
                title=title,
                url=info.get('thumburl') or info['url'],
                author=html.unescape(strip_tags(meta.get('Artist', {}).get('value', ''))).strip()[:255],
                license=meta.get('LicenseShortName', {}).get('value', '')[:100],
                license_url=meta.get('LicenseUrl', {}).get('value', ''),
                source_url=info['descriptionurl'],
            )
    return photos


def _resize(image, size, quality):
    copy = image.copy()
    copy.thumbnail((size, size), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, 'JPEG', quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def download(photo):
    """Download a photo and return (full_size_jpeg, thumbnail_jpeg) bytes."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(_get(photo.url)))).convert('RGB')
    return _resize(image, FULL_SIZE, 84), _resize(image, THUMB_SIZE, 80)


def attach(product, photo, position):
    """Download `photo` and save it as one of `product`'s gallery images."""
    from .models import ProductImage

    full, thumb = download(photo)
    name = f'{product.slug}-{position + 1}.jpg'
    image = ProductImage(
        product=product, position=position, alt=product.name, author=photo.author,
        license=photo.license, license_url=photo.license_url, source_url=photo.source_url,
    )
    image.image.save(name, ContentFile(full), save=False)
    image.thumbnail.save(name, ContentFile(thumb), save=False)
    image.save()
    return image
