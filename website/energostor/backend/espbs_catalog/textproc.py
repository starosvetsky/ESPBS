"""Text, URL and identifier hygiene for the public catalog.

Everything the API returns passes through this module: advertising tails are
cut from descriptions, seller contacts and site names disappear, images and
documents are restricted to plain HTTP(S) URLs without credentials, and all
strings are normalised to plain text (the frontend inserts them with
``textContent``).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlsplit

# --------------------------------------------------------------------------
# Limits
# --------------------------------------------------------------------------

NAME_LIMIT = 300
MPN_LIMIT = 1024
BRAND_LIMIT = 120
DESCRIPTION_LIMIT = 50000
ATTR_LIMIT = 1000
ATTR_LABEL_LIMIT = 300
ATTR_VALUE_LIMIT = 20000
DOCUMENTS_LIMIT = 20
IMAGES_LIMIT = 12
DOC_NAME_LIMIT = 200

# --------------------------------------------------------------------------
# Strings
# --------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(
    r"(?:\+7|8|7)\s*[\(\-]?\s*\d{3}\s*[\)\-]?\s*\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)
_PRICE = re.compile(r"\d[\d\s\u00a0]{0,12}(?:₽|руб\.?|р\.)\s*(?:за\s+штуку)?", re.I)


def plain_text(value, limit: int = 0) -> str:
    """Collapse whitespace, drop control characters, optionally truncate."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFC", value)
    text = _CONTROL.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def one_line(value, limit: int = 0) -> str:
    return plain_text(value, limit)


# --------------------------------------------------------------------------
# Descriptions: strip the shop's advertising tail, keep the technical part
# --------------------------------------------------------------------------

# Sentences that only sell.  A sentence is dropped when it contains one of
# these markers *and* does not look like a specification.
_SELLER_WORDS = re.compile(
    r"(олнис[а-я]*|olnisa|merlion|мерлион|наш(?:а|ей|их)\s+компан|"
    r"в\s+компании|интернет-магазин|магазин[еа]?\b)",
    re.I,
)
_PROMO_MARKERS = re.compile(
    r"(купите|купить|закажите|заказать|оформить\s+заказ|оптом|в\s+розницу|"
    r"специальн\w*\s+цен|розничн\w*\s+цен|по\s+специальной\s+цене|"
    r"по\s+телефону|заявку\s+на\s+почту|доставка|скидк|акция|"
    r"артикул\s+товара|постоянных\s+клиентов|прайс)",
    re.I,
)
_PRICE_TAIL = re.compile(
    r"\s*[-–—]?\s*(?:\d[\w-]*\s+)?[-–—]?\s*артикул\s+товара.*$", re.I
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def clean_description(raw) -> str:
    """Remove shop advertising, prices, contacts and source-site mentions."""
    if isinstance(raw, str):
        raw = re.sub(r'<br\s*/?>|</?(?:p|div|span|ul|li|strong|b)\b[^>]*>', ' ', raw, flags=re.I)
        raw = re.split(r'информацию о стоимости товара', raw, maxsplit=1, flags=re.I)[0]
        raw = re.sub(r'\+\d[\d ()-]{8,}\d', ' ', raw)
    text = plain_text(raw)
    if not text:
        return ""
    text = _URL.sub(" ", text)
    text = _EMAIL.sub(" ", text)
    text = _PHONE.sub(" ", text)
    text = _PRICE_TAIL.sub("", text)
    text = _SPACES.sub(" ", text).strip()

    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        chunk = sentence.strip(" -–—")
        if not chunk:
            continue
        if _SELLER_WORDS.search(chunk):
            continue
        promo = bool(_PROMO_MARKERS.search(chunk))
        priced = bool(_PRICE.search(chunk))
        if promo and not _looks_technical(chunk):
            continue
        if priced:
            # Прайс продавца не публикуется: оставляем предложение, только если
            # после удаления цены в нём остаётся техническое содержание.
            chunk = _PRICE.sub(" ", chunk)
            chunk = _SPACES.sub(" ", chunk).strip(" .,;:-–—")
            if not _looks_technical(chunk):
                continue
        chunk = _SPACES.sub(" ", chunk).strip()
        if chunk:
            kept.append(chunk)

    result = " ".join(kept).strip()
    result = re.sub(r"\s+([,.;:])", r"\1", result)
    return plain_text(result, DESCRIPTION_LIMIT)


_TECHNICAL = re.compile(
    r"(\d+\s*(?:в|v|а|a|квт|kw|мм|mm|кг|kg|гц|hz|ма|ma|бар|bar|°c|ip\d+|м\b|м2|м3)|"
    r"напряжен|ток\b|мощност|габарит|материал|степень\s+защиты|тип\s+|серия|"
    r"количество\s+полюс|номинал|характеристик)",
    re.I,
)


def _looks_technical(sentence: str) -> bool:
    return bool(_TECHNICAL.search(sentence))


# --------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------

def url_host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def forbidden_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return host == "olnisa.ru" or host.endswith(".olnisa.ru")


def valid_public_url(value) -> str | None:
    """Return a safe absolute HTTP(S) URL, or ``None``.

    Rejects credentials, javascript:/data: payloads, fragments-only values and
    anything that is not plain HTTP(S).
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or len(raw) > 2048:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    if not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    if any(ch in raw for ch in ("\n", "\r", "\t", "\x00")):
        return None
    # Rebuild without fragment; keep query because some CDNs need it.
    path = parts.path or "/"
    return f"{parts.scheme.lower()}://{parts.netloc}{path}" + (f"?{parts.query}" if parts.query else "")


def clean_images(values) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("url")
        url = valid_public_url(item)
        if not url:
            continue
        if forbidden_host(url_host(url)):
            continue
        if url not in result:
            result.append(url)
        if len(result) >= IMAGES_LIMIT:
            break
    return result


def clean_documents(values) -> list[dict]:
    if not isinstance(values, list):
        return []
    result: list[dict] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        url = valid_public_url(item.get("url"))
        if not url or forbidden_host(url_host(url)):
            continue
        name = plain_text(item.get("name"), DOC_NAME_LIMIT) or url.rsplit("/", 1)[-1]
        entry = {"name": name, "url": url}
        if entry not in result:
            result.append(entry)
        if len(result) >= DOCUMENTS_LIMIT:
            break
    return result


# --------------------------------------------------------------------------
# Attributes
# --------------------------------------------------------------------------

def clean_attributes(value) -> list[dict]:
    if not isinstance(value, dict):
        return []
    result: list[dict] = []
    for label, raw in value.items():
        key = plain_text(label, ATTR_LABEL_LIMIT)
        if not key:
            continue
        if isinstance(raw, (list, tuple)):
            parts = [plain_text(item, ATTR_VALUE_LIMIT) for item in raw]
            text = "; ".join(part for part in parts if part)
        else:
            text = plain_text(raw, ATTR_VALUE_LIMIT)
        text = text.strip()
        if not text:
            continue
        result.append({"label": key, "value": text})
        if len(result) >= ATTR_LIMIT:
            break
    return result


# --------------------------------------------------------------------------
# Identifiers
# --------------------------------------------------------------------------

_BRAND_CLEAN = re.compile(r"[^a-z0-9]+")
_MPN_CLEAN = re.compile(r"\s+")


def normalize_brand(brand) -> str:
    return plain_text(brand, BRAND_LIMIT)


def normalize_mpn(mpn) -> str:
    # Preserve exact case, punctuation and internal spacing for identity.
    return mpn.strip() if isinstance(mpn, str) else ""


def is_usable_mpn(mpn: str) -> bool:
    """An MPN must carry at least one letter or digit and be reasonably short."""
    if not mpn or len(mpn) < 2:
        return False
    if not re.search(r"[A-Z0-9]", mpn):
        return False
    if mpn in {"НЕТ", "N/A", "NA", "-", "—", "БЕЗ АРТИКУЛА"}:
        return False
    return True


def dedupe_key(brand: str, mpn: str) -> str | None:
    """Confirmed brand + exact MPN; only the brand is case-insensitive.

    Returns ``None`` when either part is missing — such records are never
    merged with anything else.
    """
    brand = _SPACES.sub(" ", (brand or "").strip()).casefold()
    mpn = (mpn or "").strip()
    if not brand or not is_usable_mpn(mpn.upper()):
        return None
    return f"{brand}|{mpn}"


def product_id_for_key(key: str) -> str:
    return hashlib.sha1(("key:" + key).encode("utf-8")).hexdigest()[:16]


def product_id_for_record(record_id: str) -> str:
    return hashlib.sha1(("record:" + record_id).encode("utf-8")).hexdigest()[:16]


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(value: str, fallback: str = "brand") -> str:
    text = plain_text(value).casefold()
    out = []
    for char in text:
        if char in _TRANSLIT:
            out.append(_TRANSLIT[char])
        elif char.isalnum() and char.isascii():
            out.append(char)
        else:
            out.append("-")
    slug = _BRAND_CLEAN.sub("-", "".join(out)).strip("-")
    return slug[:64] or fallback


def build_search_text(*parts: str) -> str:
    return plain_text(" ".join(part for part in parts if part), 1200).casefold()


def short_summary(description: str, limit: int = 180) -> str:
    text = plain_text(description)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def category_path_from_url(url: str, known: set[str]) -> str:
    """Best-effort source category path from a product URL.

    Tries the longest suffix of the URL path that is a known category path,
    so ``/manufacturers/x/nizkovoltnoe-oborudovanie/shkafnaya-produkcziya/``
    becomes ``nizkovoltnoe-oborudovanie/shkafnaya-produkcziya``.
    """
    if not isinstance(url, str):
        return ""
    try:
        path = unquote(urlsplit(url).path)
    except ValueError:
        return ""
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        return ""
    lowered = [seg.lower() for seg in segments]
    # Берём самое глубокое известное сочетание сегментов: в URL магазина
    # категория стоит в конце (/manufacturers/<brand>/<категория>/), а хвост
    # может содержать пагинацию или подстраницу.
    for start in range(len(lowered) - 1, -1, -1):
        for end in range(len(lowered), start, -1):
            candidate = "/".join(lowered[start:end])
            if candidate in known:
                return candidate
    # Not a known audited path: fall back to the last two / one segments.
    if len(lowered) >= 2:
        return "/".join(lowered[-2:])
    return lowered[-1]
