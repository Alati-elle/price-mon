#!/usr/bin/env python3
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from update_prices import (
    PRICES_PATH,
    PRODUCTS_PATH,
    build_observation,
    compact_text,
    detect_marketplace,
    load_json,
    save_json,
)


MARKETPLACE_TITLES = {
    "wildberries": "Wildberries",
    "ozon": "Ozon",
    "yandex_market": "Яндекс Маркет",
    "aliexpress": "AliExpress",
    "generic": "Другая площадка",
}


def normalize_url(value):
    value = (value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Нужна полная http(s)-ссылка на карточку товара")
    return value


def product_id_from_url(url):
    parsed = urlparse(url)
    wb_match = re.search(r"/catalog/(\d+)", parsed.path)
    if wb_match:
        return f"wb-{wb_match.group(1)}"

    slug = re.sub(r"[^a-z0-9]+", "-", parsed.netloc.lower().removeprefix("www.")).strip("-")
    return f"{slug}-{stable_hash(url)[:10]}"


def stable_hash(value):
    hash_value = 5381
    for char in value:
        hash_value = ((hash_value << 5) + hash_value) + ord(char)
    return format(hash_value & 0xFFFFFFFF, "x")


def add_product(url):
    url = normalize_url(url)
    products = load_json(PRODUCTS_PATH, [])
    prices = load_json(PRICES_PATH, {})
    marketplace = detect_marketplace(url)
    parsed = urlparse(url)
    product_id = product_id_from_url(url)
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    product = next((item for item in products if item.get("id") == product_id or item.get("url") == url), None)
    if product is None:
        product = {
            "id": product_id,
            "title": f"{MARKETPLACE_TITLES.get(marketplace, MARKETPLACE_TITLES['generic'])} · {product_id}",
            "url": url,
            "store": parsed.netloc.lower().removeprefix("www."),
            "marketplace": marketplace,
            "currency": "RUB",
            "active": True,
        }
        products.insert(0, product)
    else:
        product["url"] = url
        product["active"] = True
        product.setdefault("marketplace", marketplace)
        product.setdefault("store", parsed.netloc.lower().removeprefix("www."))
        product.setdefault("currency", "RUB")

    observation = build_observation(product, checked_at)
    if observation.get("resolved_url"):
        product["resolved_url"] = observation["resolved_url"]
        product["marketplace"] = detect_marketplace(observation["resolved_url"])
    if observation.get("image_url"):
        product["image_url"] = observation["image_url"]
    if observation.get("currency"):
        product["currency"] = observation["currency"]
    if observation.get("title"):
        product["title"] = compact_text(observation["title"])

    prices.setdefault(product["id"], []).append(observation)
    save_json(PRODUCTS_PATH, products)
    save_json(PRICES_PATH, prices)
    return product, observation


def main():
    parser = argparse.ArgumentParser(description="Add a product URL and collect the first price observation.")
    parser.add_argument("url", help="Product card URL")
    args = parser.parse_args()

    product, observation = add_product(args.url)
    print(json.dumps({"product": product, "observation": observation}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
