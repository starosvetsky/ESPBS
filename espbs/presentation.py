"""Customer-facing product projection; raw snapshots keep traceability fields."""


PUBLIC_FIELDS = ('name', 'brand', 'manufacturer', 'mpn', 'article', 'sku',
                 'category', 'description', 'attributes')
OFFER_FIELDS = ('price', 'price_text', 'currency', 'availability')


def public_product(record):
    """Return product data without collector identity, URLs or provenance."""
    result = {key: record[key] for key in PUBLIC_FIELDS if key in record}
    offer = record.get('offer')
    if isinstance(offer, dict):
        result['offer'] = {key: offer[key] for key in OFFER_FIELDS if key in offer}
    images = record.get('images')
    if isinstance(images, list):
        # Image URLs are needed by the card, but Olnisa images stay forbidden.
        from .photos import forbidden
        result['images'] = [url for url in images
                            if isinstance(url, str) and not forbidden(url)]
    documents = record.get('documents')
    if isinstance(documents, list):
        result['documents'] = [
            {key: item[key] for key in ('name', 'url') if key in item}
            for item in documents if isinstance(item, dict) and isinstance(item.get('url'), str)
        ]
    return result
