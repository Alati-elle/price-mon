#!/usr/bin/env python3
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_prices

PRODUCTS_PATH = ROOT / "data" / "products.json"
PRICES_PATH = ROOT / "data" / "prices.json"

LABELS = {
    "wildberries": "Wildberries",
    "ozon": "Ozon",
    "yandex_market": "Яндекс Маркет",
    "aliexpress": "AliExpress",
    "generic": "Другая площадка",
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


def product_id_from_url(url):
    parsed = urlparse(url)
    wb_match = re.search(r"/catalog/(\d+)", parsed.path)
    if wb_match:
        return f"wb-{wb_match.group(1)}"

    host = re.sub(r"^www\.", "", parsed.hostname or "product")
    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-") or "product"
    suffix = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{suffix}"


def extract_url(issue):
    body = issue.get("body") or ""
    explicit = re.search(r"(?:URL|Ссылка)\s*:\s*(https?://\S+)", body, re.IGNORECASE)
    if explicit:
        return explicit.group(1).rstrip("`.,;>)\n\r")

    generic = re.search(r"https?://\S+", body)
    if generic:
        return generic.group(0).rstrip("`.,;>)\n\r")
    raise ValueError("Product URL was not found in issue body")


def normalize_product_url(url):
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Product URL must be an absolute http(s) link")
    return parsed.geturl()


def write_output(**values):
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        for key, value in values.items():
            print(f"{key}={value}")
        return

    with open(output_path, "a", encoding="utf-8") as file:
        for key, value in values.items():
            file.write(f"{key}={value}\n")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: add_product_request.py <github-event-path>")

    event = load_json(Path(sys.argv[1]), {})
    issue = event.get("issue") or {}
    url = normalize_product_url(extract_url(issue))
    marketplace = update_prices.detect_marketplace(url)
    parsed = urlparse(url)
    product_id = product_id_from_url(url)

    products = load_json(PRODUCTS_PATH, [])
    prices = load_json(PRICES_PATH, {})

    existing = next((item for item in products if item.get("id") == product_id or item.get("url") == url), None)
    if existing:
        existing["active"] = True
        existing.setdefault("marketplace", marketplace)
        existing.setdefault("currency", "RUB")
        save_json(PRODUCTS_PATH, products)
        write_output(product_id=existing["id"], product_url=url, result="exists")
        print(f"Product already exists: {existing['id']}")
        return 0

    product = {
        "id": product_id,
        "title": LABELS.get(marketplace, marketplace),
        "url": url,
        "store": re.sub(r"^www\.", "", parsed.hostname or ""),
        "marketplace": marketplace,
        "currency": "RUB",
        "active": True,
    }

    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    observation = update_prices.build_observation(product, checked_at)
    if observation.get("title"):
        product["title"] = observation["title"]

    products.insert(0, product)
    prices.setdefault(product_id, []).append(observation)

    save_json(PRODUCTS_PATH, products)
    save_json(PRICES_PATH, prices)
    write_output(product_id=product_id, product_url=url, result="added")
    print(f"Added product: {product_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
