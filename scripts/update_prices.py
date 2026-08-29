#!/usr/bin/env python3
import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_PATH = ROOT / "data" / "products.json"
PRICES_PATH = ROOT / "data" / "prices.json"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 PriceMonitor/1.0"
)

CURRENCY_BY_SYMBOL = {
    "₽": "RUB",
    "руб": "RUB",
    "р": "RUB",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def fetch_html(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def compact_text(value):
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def parse_number(value):
    if value is None:
        return None

    normalized = str(value).strip()
    normalized = re.sub(r"[^\d,.]", "", normalized)
    if not normalized:
        return None

    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(" ", "").replace(",", ".")
    else:
        normalized = normalized.replace(" ", "")

    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return None

    if number <= 0:
        return None

    return float(number)


def normalize_price(value):
    if value is None:
        return None
    if abs(value - round(value)) < 0.001:
        return int(round(value))
    return round(value, 2)


def find_json_ld_objects(page):
    objects = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(page):
        raw = compact_text(match.group(1))
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            objects.extend(parsed)
        elif isinstance(parsed, dict):
            objects.append(parsed)
    return objects


def iter_nested_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_nested_json(child)
    elif isinstance(value, list):
        for item in value:
            yield from iter_nested_json(item)


def price_from_json_ld(page):
    for obj in find_json_ld_objects(page):
        for item in iter_nested_json(obj):
            item_type = item.get("@type")
            if isinstance(item_type, list):
                is_offer = any(str(value).lower() == "offer" for value in item_type)
            else:
                is_offer = str(item_type).lower() == "offer"

            if not is_offer and "price" not in item:
                continue

            price = parse_number(item.get("price") or item.get("lowPrice"))
            if price is None:
                continue

            currency = item.get("priceCurrency") or item.get("currency")
            return normalize_price(price), str(currency or "").upper() or None

    return None, None


def price_from_meta(page):
    meta_patterns = [
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']product:price:amount["\']',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']price["\']',
    ]
    currency_patterns = [
        r'<meta[^>]+property=["\']product:price:currency["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']priceCurrency["\'][^>]+content=["\']([^"\']+)["\']',
    ]

    price = None
    currency = None
    for pattern in meta_patterns:
        match = re.search(pattern, page, re.IGNORECASE)
        if match:
            price = parse_number(match.group(1))
            break

    for pattern in currency_patterns:
        match = re.search(pattern, page, re.IGNORECASE)
        if match:
            currency = compact_text(match.group(1)).upper()
            break

    return normalize_price(price), currency


def price_from_text(page):
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", page, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = compact_text(re.sub(r"<[^>]+>", " ", text))
    pattern = re.compile(r"(?<!\d)(\d[\d\s.,]{1,14})\s*(₽|руб\.?|р\.?|\$|€|£)(?!\w)", re.IGNORECASE)

    candidates = []
    for match in pattern.finditer(text):
        price = parse_number(match.group(1))
        if price is None:
            continue
        symbol = match.group(2).lower().replace(".", "")
        currency = CURRENCY_BY_SYMBOL.get(symbol, CURRENCY_BY_SYMBOL.get(match.group(2), "RUB"))
        candidates.append((price, currency))

    if not candidates:
        return None, None

    candidates.sort(key=lambda item: item[0])
    price, currency = candidates[0]
    return normalize_price(price), currency


def extract_price(page, fallback_currency):
    for extractor in (price_from_json_ld, price_from_meta, price_from_text):
        price, currency = extractor(page)
        if price is not None:
            return price, currency or fallback_currency or "RUB"
    return None, fallback_currency or "RUB"


def build_observation(product, checked_at):
    try:
        page = fetch_html(product["url"])
        price, currency = extract_price(page, product.get("currency"))
        if price is None:
            return {
                "checked_at": checked_at,
                "price": None,
                "currency": product.get("currency", "RUB"),
                "status": "error",
                "message": "price not found",
            }

        return {
            "checked_at": checked_at,
            "price": price,
            "currency": currency,
            "status": "ok",
            "message": "parsed",
        }
    except (urllib.error.URLError, TimeoutError, KeyError) as exc:
        return {
            "checked_at": checked_at,
            "price": None,
            "currency": product.get("currency", "RUB"),
            "status": "error",
            "message": str(exc)[:180],
        }


def update_prices(dry_run=False):
    products = load_json(PRODUCTS_PATH, [])
    prices = load_json(PRICES_PATH, {})
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    changed = False
    for product in products:
        if not product.get("active", True):
            continue

        observation = build_observation(product, checked_at)
        prices.setdefault(product["id"], []).append(observation)
        changed = True
        print(f"{product['id']}: {observation['status']} {observation.get('price')}")

    if changed and not dry_run:
        save_json(PRICES_PATH, prices)

    return changed


def main():
    parser = argparse.ArgumentParser(description="Update product prices.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch prices without writing data/prices.json.")
    args = parser.parse_args()

    update_prices(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
