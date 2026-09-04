import json
import os
from html import escape
from typing import Any

import requests


STATE_FILE = os.environ.get("STATE_FILE", "listing_state.json")
SEARCH_TERM = os.environ.get("SEARCH_TERM", "hot wheels")


def json_env(name: str, default: Any) -> Any:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        print(f"Invalid JSON in {name}; provider skipped.")
        return default


def location_values() -> dict[str, str]:
    latitude = os.environ.get("DELIVERY_LATITUDE")
    longitude = os.environ.get("DELIVERY_LONGITUDE")
    if not latitude or not longitude:
        raise RuntimeError("DELIVERY_LATITUDE and DELIVERY_LONGITUDE are required secrets")
    return {"LATITUDE": latitude, "LONGITUDE": longitude, "SEARCH_TERM": SEARCH_TERM}


def replace_placeholders(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str):
        for name, replacement in values.items():
            value = value.replace(f"${{{name}}}", replacement)
        return value
    if isinstance(value, list):
        return [replace_placeholders(item, values) for item in value]
    if isinstance(value, dict):
        return {key: replace_placeholders(item, values) for key, item in value.items()}
    return value


def load_state() -> dict[str, dict[str, Any]]:
    try:
        with open(STATE_FILE, encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    if isinstance(state, list):
        return {item: {"available": True} for item in state}
    return state if isinstance(state, dict) else {}


def save_state(state: dict[str, dict[str, Any]]) -> None:
    temporary_file = f"{STATE_FILE}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2, sort_keys=True)
    os.replace(temporary_file, STATE_FILE)


def product_available(product: dict[str, Any]) -> bool:
    for key in ("available", "is_available", "in_stock"):
        if key in product:
            value = product[key]
            if isinstance(value, str):
                return value.strip().lower() in {"true", "yes", "1", "available", "in_stock"}
            return bool(value)
    for key in ("inventory", "stock", "quantity"):
        if key in product:
            try:
                return float(product[key]) > 0
            except (TypeError, ValueError):
                return False
    status = str(product.get("status", "")).lower()
    if status:
        return status in {"available", "in_stock", "instock", "active"}
    return False


def extract_products(value: Any, provider: str, default_url: str) -> list[dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    if isinstance(value, list):
        for item in value:
            for product in extract_products(item, provider, default_url):
                products[product["id"]] = product
    elif isinstance(value, dict):
        product_id = value.get("product_id") or value.get("item_id") or value.get("variant_id")
        product_id = product_id or value.get("id")
        title = value.get("name") or value.get("title") or value.get("product_name")
        if product_id is not None and isinstance(title, str) and SEARCH_TERM.lower() in title.lower():
            product = {
                "id": f"{provider}:{product_id}",
                "title": title,
                "url": value.get("url") or value.get("product_url") or default_url,
                "provider": provider,
                "available": product_available(value),
            }
            products[product["id"]] = product
        for child in value.values():
            for product in extract_products(child, provider, default_url):
                products[product["id"]] = product
    return list(products.values())


def check_provider(config: dict[str, Any], values: dict[str, str]) -> tuple[bool, list[dict[str, Any]]]:
    name = config["name"]
    url = replace_placeholders(config.get("url"), values)
    headers = replace_placeholders(config.get("headers", {}), values)
    body = replace_placeholders(config.get("body", {}), values)
    if not url or not headers:
        print(f"Skipping {name}: URL or headers are not configured.")
        return False, []

    try:
        method = str(config.get("method", "GET")).upper()
        request = requests.post if method == "POST" else requests.get
        response = request(url, headers=headers, json=body if method == "POST" else None, timeout=20)
        response.raise_for_status()
        products = extract_products(response.json(), name, config.get("default_url", url))
        print(f"{name}: found {len(products)} matching listings.")
        return True, products
    except (requests.RequestException, ValueError) as error:
        print(f"{name} failed: {error}")
        return False, []


def providers() -> list[dict[str, Any]]:
    return [
        {
            "name": "Blinkit",
            "url": "https://blinkit.com/v1/layout/search?q=hot+wheels",
            "headers": json_env("BLINKIT_HEADERS", {}),
            "method": "POST",
            "body": json_env("BLINKIT_BODY", {}),
            "default_url": "https://blinkit.com",
        },
        {
            "name": "Zepto",
            "url": os.environ.get("ZEPTO_SEARCH_URL"),
            "headers": json_env("ZEPTO_HEADERS", {}),
            "method": os.environ.get("ZEPTO_METHOD", "GET"),
            "body": json_env("ZEPTO_BODY", {}),
            "default_url": "https://www.zeptonow.com",
        },
        {
            "name": "Instamart",
            "url": os.environ.get("INSTAMART_SEARCH_URL"),
            "headers": json_env("INSTAMART_HEADERS", {}),
            "method": os.environ.get("INSTAMART_METHOD", "GET"),
            "body": json_env("INSTAMART_BODY", {}),
            "default_url": "https://www.swiggy.com/instamart",
        },
    ]


def send_telegram(products: list[dict[str, Any]]) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram credentials are missing; state will not be advanced.")
        return False

    for start in range(0, len(products), 5):
        lines = ["<b>Hot Wheels listing update</b>", ""]
        for product in products[start:start + 5]:
            lines.extend([
                f"<b>{escape(product['provider'])}</b>",
                escape(product["title"]),
                f"<a href=\"{escape(product['url'], quote=True)}\">Open listing</a>",
                "",
            ])
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"},
                timeout=15,
            )
            response.raise_for_status()
            if not response.json().get("ok"):
                return False
        except (requests.RequestException, ValueError) as error:
            print(f"Telegram failed: {error}")
            return False
    return True


def main() -> None:
    values = location_values()
    state = load_state()
    current: dict[str, dict[str, Any]] = {}
    successful_providers: set[str] = set()

    for config in providers():
        success, products = check_provider(config, values)
        if success:
            successful_providers.add(config["name"])
            for product in products:
                current[product["id"]] = product

    alerts = []
    for product_id, product in current.items():
        previous = state.get(product_id, {})
        if product["available"] and not previous.get("available", False):
            alerts.append(product)
        state[product_id] = {"available": product["available"], **product}

    for product_id, previous in state.items():
        provider = str(previous.get("provider", product_id.split(":", 1)[0]))
        if provider in successful_providers and product_id not in current:
            previous["available"] = False

    if alerts:
        print(f"Found {len(alerts)} new or restocked available listings.")
        if not send_telegram(alerts):
            return
    else:
        print("No new or restocked available listings.")
    save_state(state)


if __name__ == "__main__":
    main()
