#!/usr/bin/env python3
import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse


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

MARKETPLACE_HOSTS = {
    "wildberries": ("wildberries.ru", "wb.ru"),
    "ozon": ("ozon.ru",),
    "yandex_market": ("market.yandex.ru",),
    "aliexpress": ("aliexpress.ru", "aliexpress.com"),
}


@dataclass
class PriceResult:
    price: float | int | None
    currency: str
    title: str | None = None
    source: str = "html"


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


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


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


def detect_marketplace(url):
    host = urlparse(url).hostname or ""
    host = host.lower().removeprefix("www.")
    for marketplace, hosts in MARKETPLACE_HOSTS.items():
        if any(host == item or host.endswith("." + item) for item in hosts):
            return marketplace
    return "generic"


def extract_title_from_meta(page):
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r"<title[^>]*>(.*?)</title>",
    ]
    for pattern in patterns:
        match = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if match:
            title = compact_text(match.group(1))
            title = re.sub(r"\s+[|–-]\s+.*$", "", title).strip()
            if title:
                return title
    return None


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
            title = item.get("name") or extract_title_from_meta(page)
            return normalize_price(price), str(currency or "").upper() or None, title

    return None, None, None


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

    return normalize_price(price), currency, extract_title_from_meta(page)


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
        return None, None, None

    candidates.sort(key=lambda item: item[0])
    price, currency = candidates[0]
    return normalize_price(price), currency, extract_title_from_meta(page)


def extract_price(page, fallback_currency):
    for extractor in (price_from_json_ld, price_from_meta, price_from_text):
        price, currency, title = extractor(page)
        if price is not None:
            return PriceResult(price, currency or fallback_currency or "RUB", title)
    return PriceResult(None, fallback_currency or "RUB", extract_title_from_meta(page))


def extract_wb_article(url):
    match = re.search(r"/catalog/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"\b(?:nm|card)=(\d+)", url)
    return match.group(1) if match else None


def parse_wb_price(url, fallback_currency):
    article = extract_wb_article(url)
    if not article:
        return PriceResult(None, fallback_currency or "RUB", source="wildberries-api")

    endpoint = f"https://card.wb.ru/cards/v4/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={article}"
    data = fetch_json(endpoint)
    products = data.get("data", {}).get("products") or data.get("products", [])
    if not products:
        return PriceResult(None, fallback_currency or "RUB", source="wildberries-api")

    item = products[0]
    sizes = item.get("sizes") or []
    prices = []
    for size in sizes:
        price_info = size.get("price") or {}
        total = price_info.get("total")
        product_part = price_info.get("product")
        logistics_part = price_info.get("logistics")
        if isinstance(total, (int, float)) and total > 0:
            prices.append(total / 100)
        elif isinstance(product_part, (int, float)) and product_part > 0:
            logistics = logistics_part if isinstance(logistics_part, (int, float)) else 0
            prices.append((product_part + logistics) / 100)
        else:
            basic = price_info.get("basic")
            if isinstance(basic, (int, float)) and basic > 0:
                prices.append(basic / 100)

    direct_price = item.get("salePriceU") or item.get("priceU")
    if isinstance(direct_price, (int, float)) and direct_price > 0:
        prices.append(direct_price / 100)

    price = min(prices) if prices else None
    title = compact_text(" ".join(part for part in [item.get("brand"), item.get("name")] if part))
    return PriceResult(normalize_price(price), "RUB", title or None, "wildberries-api")


def parse_embedded_json_price(page, fallback_currency, marketplace):
    candidates = []
    title = extract_title_from_meta(page)
    patterns = [
        r'"(?:price|finalPrice|currentPrice|salePrice|discountPrice)"\s*:\s*"?(\d[\d\s.,]*)"?',
        r'"(?:priceValue|value)"\s*:\s*"?(\d[\d\s.,]*)"?\s*,\s*"(?:currency|priceCurrency)"\s*:\s*"([A-Z]{3})"',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, page, re.IGNORECASE):
            price = parse_number(match.group(1))
            if price is None:
                continue
            currency = match.group(2).upper() if len(match.groups()) > 1 and match.group(2) else fallback_currency or "RUB"
            if marketplace == "aliexpress" and price > 10_000_000:
                price = price / 100
            candidates.append((price, currency))

    if not candidates:
        return PriceResult(None, fallback_currency or "RUB", title, f"{marketplace}-embedded-json")

    candidates.sort(key=lambda item: item[0])
    price, currency = candidates[0]
    return PriceResult(normalize_price(price), currency, title, f"{marketplace}-embedded-json")


def parse_marketplace_price(product):
    url = product["url"]
    marketplace = product.get("marketplace") or detect_marketplace(url)
    fallback_currency = product.get("currency", "RUB")

    if marketplace == "wildberries":
        result = parse_wb_price(url, fallback_currency)
        if result.price is not None:
            return result

    page = fetch_html(url)
    if marketplace in {"ozon", "yandex_market", "aliexpress"}:
        result = parse_embedded_json_price(page, fallback_currency, marketplace)
        if result.price is not None:
            return result

    result = extract_price(page, fallback_currency)
    result.source = marketplace if marketplace != "generic" else result.source
    return result


def build_observation(product, checked_at):
    try:
        result = parse_marketplace_price(product)
        if result.price is None:
            return {
                "checked_at": checked_at,
                "price": None,
                "currency": result.currency,
                "status": "error",
                "message": "price not found",
            }

        return {
            "checked_at": checked_at,
            "price": result.price,
            "currency": result.currency,
            "status": "ok",
            "message": result.source,
            "title": result.title,
        }
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
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
        if observation.get("title") and not product.get("title"):
            product["title"] = observation["title"]
        product.setdefault("marketplace", detect_marketplace(product["url"]))
        prices.setdefault(product["id"], []).append(observation)
        changed = True
        print(f"{product['id']}: {observation['status']} {observation.get('price')}")

    if changed and not dry_run:
        save_json(PRODUCTS_PATH, products)
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
