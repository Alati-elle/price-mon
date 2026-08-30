#!/usr/bin/env python3
import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlparse


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
    "aliexpress": ("aliexpress.ru", "aliexpress.com", "ali.click"),
}

SHORT_LINK_HOSTS = {"ali.click", "ozon.ru"}


@dataclass
class PriceResult:
    price: float | int | None
    currency: str
    title: str | None = None
    source: str = "html"
    image_url: str | None = None
    resolved_url: str | None = None


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


def request_headers(accept):
    return {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_html(url):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    request = urllib.request.Request(
        url,
        headers=request_headers("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    )
    with opener.open(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_html_with_browser_redirects(url):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    request = urllib.request.Request(
        url,
        headers=request_headers("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    )
    with opener.open(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.geturl(), response.read().decode(charset, errors="replace")


def resolve_url(url, limit=8):
    try:
        resolved_url, _ = fetch_html_with_browser_redirects(url)
        if resolved_url != url:
            return resolved_url
    except urllib.error.URLError:
        pass

    current = url
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(CookieJar()))
    seen = set()
    for _ in range(limit):
        if current in seen:
            break
        seen.add(current)
        request = urllib.request.Request(
            current,
            headers=request_headers("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
            method="HEAD",
        )
        try:
            opener.open(request, timeout=20)
            return current
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                return current
            location = exc.headers.get("Location")
            if not location:
                return current
            next_url = urljoin(current, location)
            parsed_next = urlparse(next_url)
            if parsed_next.netloc.endswith("login.aliexpress.ru"):
                return current
            current = next_url
    return current


def normalized_product_url(url):
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host in SHORT_LINK_HOSTS:
        return resolve_url(url)
    return url


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
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


def extract_image_from_meta(page):
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if match:
            image_url = html.unescape(match.group(1)).strip()
            if image_url.startswith("//"):
                return "https:" + image_url
            if image_url.startswith("http://") or image_url.startswith("https://"):
                return image_url
    return None


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
    image_url = extract_image_from_meta(page)
    for extractor in (price_from_json_ld, price_from_meta, price_from_text):
        price, currency, title = extractor(page)
        if price is not None:
            return PriceResult(price, currency or fallback_currency or "RUB", title, image_url=image_url)
    return PriceResult(None, fallback_currency or "RUB", extract_title_from_meta(page), image_url=image_url)


def extract_wb_article(url):
    match = re.search(r"/catalog/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"\b(?:nm|card)=(\d+)", url)
    return match.group(1) if match else None


def wb_image_candidates(article):
    nm = int(article)
    vol = nm // 100000
    part = nm // 1000
    urls = []
    for basket in range(1, 61):
        host = f"basket-{basket:02d}.wbbasket.ru" if basket < 10 else f"basket-{basket}.wbbasket.ru"
        base = f"https://{host}/vol{vol}/part{part}/{article}/images"
        urls.extend([f"{base}/big/1.webp", f"{base}/c516x688/1.webp", f"{base}/tm/1.webp"])
    return urls


def first_wb_image(article):
    for image_url in wb_image_candidates(article):
        request = urllib.request.Request(image_url, headers=request_headers("image/avif,image/webp,image/*,*/*"), method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if 200 <= response.status < 400:
                    return image_url
        except urllib.error.URLError:
            continue
    return wb_image_candidates(article)[0]


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

    title = compact_text(" ".join(part for part in [item.get("brand"), item.get("name")] if part))
    image_url = first_wb_image(article)
    if not prices and item.get("totalQuantity") == 0:
        return PriceResult(None, "RUB", title or None, "wildberries-out-of-stock", image_url, url)

    price = min(prices) if prices else None
    return PriceResult(normalize_price(price), "RUB", title or None, "wildberries-api", image_url, url)


def parse_embedded_json_price(page, fallback_currency, marketplace):
    candidates = []
    title = extract_title_from_meta(page)
    image_url = extract_image_from_meta(page)
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
        return PriceResult(None, fallback_currency or "RUB", title, f"{marketplace}-embedded-json", image_url)

    candidates.sort(key=lambda item: item[0])
    price, currency = candidates[0]
    return PriceResult(normalize_price(price), currency, title, f"{marketplace}-embedded-json", image_url)


def parse_ali_price_with_browser(url, fallback_currency):
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                user_agent=USER_AGENT,
                extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(3_000)

                resolved_url = page.url
                title = compact_text(page.title()) or None
                image_locator = page.locator("meta[property='og:image']")
                image_url = image_locator.first.get_attribute("content") if image_locator.count() else None
                if image_url and image_url.startswith("//"):
                    image_url = "https:" + image_url

                body_text = compact_text(page.locator("body").inner_text(timeout=10_000))
                if re.search(r"captcha|подозрительн|robot|verify", body_text, re.IGNORECASE):
                    return PriceResult(None, fallback_currency or "RUB", title, "aliexpress-captcha", image_url, resolved_url)

                candidates = []
                for match in re.finditer(r"(?<!\d)(\d[\d\s\u00a0.,]{1,14})\s*(?:₽|руб\.?|RUB)(?!\w)", body_text, re.IGNORECASE):
                    price = parse_number(match.group(1))
                    if price is not None and 20 <= price <= 10_000_000:
                        candidates.append(price)

                if candidates:
                    return PriceResult(normalize_price(min(candidates)), "RUB", title, "aliexpress-browser", image_url, resolved_url)

                return PriceResult(None, fallback_currency or "RUB", title, "aliexpress-browser", image_url, resolved_url)
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        return PriceResult(None, fallback_currency or "RUB", None, f"aliexpress-browser unavailable: {str(exc)[:120]}", None, url)


def parse_marketplace_price(product):
    url = normalized_product_url(product["url"])
    marketplace = detect_marketplace(url) if url != product["url"] else (product.get("marketplace") or detect_marketplace(url))
    fallback_currency = product.get("currency", "RUB")

    if marketplace == "wildberries":
        result = parse_wb_price(url, fallback_currency)
        if result.price is not None or result.source == "wildberries-out-of-stock":
            return result

    try:
        page = fetch_html(url)
    except urllib.error.URLError:
        if marketplace == "aliexpress":
            browser_result = parse_ali_price_with_browser(url, fallback_currency)
            if browser_result is not None:
                return browser_result
        raise

    if marketplace in {"ozon", "yandex_market", "aliexpress"}:
        result = parse_embedded_json_price(page, fallback_currency, marketplace)
        if result.price is not None:
            result.resolved_url = url
            return result
        if marketplace == "aliexpress":
            browser_result = parse_ali_price_with_browser(url, fallback_currency)
            if browser_result is not None:
                return browser_result

    result = extract_price(page, fallback_currency)
    result.source = marketplace if marketplace != "generic" else result.source
    result.resolved_url = url
    return result


def build_observation(product, checked_at):
    try:
        result = parse_marketplace_price(product)
        if result.price is None:
            observation = {
                "checked_at": checked_at,
                "price": None,
                "currency": result.currency,
                "status": "error",
                "message": result.source if result.source != "html" else "price not found",
            }
            if result.title:
                observation["title"] = result.title
            if result.image_url:
                observation["image_url"] = result.image_url
            if result.resolved_url and result.resolved_url != product.get("url"):
                observation["resolved_url"] = result.resolved_url
            return observation

        observation = {
            "checked_at": checked_at,
            "price": result.price,
            "currency": result.currency,
            "status": "ok",
            "message": result.source,
        }
        if result.title:
            observation["title"] = result.title
        if result.image_url:
            observation["image_url"] = result.image_url
        if result.resolved_url and result.resolved_url != product.get("url"):
            observation["resolved_url"] = result.resolved_url
        return observation
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
        if observation.get("resolved_url"):
            product["resolved_url"] = observation["resolved_url"]
            product["marketplace"] = detect_marketplace(observation["resolved_url"])
        if observation.get("image_url"):
            product["image_url"] = observation["image_url"]
        current_title = compact_text(product.get("title"))
        technical_title = current_title in {
            "",
            product.get("url", ""),
            product.get("store", ""),
            "Wildberries",
            "Ozon",
            "Яндекс Маркет",
            "AliExpress",
            "Другая площадка",
        } or current_title.startswith(("Wildberries · ", "Ozon · ", "AliExpress · ", "Другая площадка · "))
        if observation.get("title") and technical_title:
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
