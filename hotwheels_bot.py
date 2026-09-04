import os
import json
from html import escape
import requests

# --- CONFIGURATION ---
# Telegram Settings (Set these in GitHub Secrets)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# State File to remember what we've already alerted you about
STATE_FILE = "seen_products.json"

# Quick Commerce configuration. Capture these from each app's browser network panel.
def load_json_env(name):
    value = os.environ.get(name, "{}")
    try:
        return json.loads(value) if value else {}
    except json.JSONDecodeError:
        print(f"Ignoring invalid JSON in {name}.")
        return {}


BLINKIT_HEADERS = load_json_env("BLINKIT_HEADERS")
ZEPTO_HEADERS = load_json_env("ZEPTO_HEADERS")
INSTAMART_HEADERS = load_json_env("INSTAMART_HEADERS")
ZEPTO_SEARCH_URL = os.environ.get("ZEPTO_SEARCH_URL")
INSTAMART_SEARCH_URL = os.environ.get("INSTAMART_SEARCH_URL")
ZEPTO_METHOD = os.environ.get("ZEPTO_METHOD", "GET").upper()
INSTAMART_METHOD = os.environ.get("INSTAMART_METHOD", "GET").upper()
ZEPTO_BODY = load_json_env("ZEPTO_BODY")
INSTAMART_BODY = load_json_env("INSTAMART_BODY")

def load_seen_products():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except:
                return set()
    return set()

def save_seen_products(seen_set):
    with open(STATE_FILE, 'w') as f:
        json.dump(sorted(seen_set), f)

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing; alert was not recorded as sent:")
        print(message)
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        if not response.json().get("ok", False):
            print("Telegram rejected the alert.")
            return False
        return True
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
        return False

def extract_products(value, store_name, default_url):
    """Find product-shaped records in a provider's nested JSON response."""
    products = []
    if isinstance(value, list):
        for item in value:
            products.extend(extract_products(item, store_name, default_url))
    elif isinstance(value, dict):
        product_id = value.get('product_id') or value.get('item_id') or value.get('id')
        title = value.get('name') or value.get('title') or value.get('product_name')
        if product_id is not None and isinstance(title, str) and "hot wheels" in title.lower():
            link = value.get('url') or value.get('product_url') or default_url
            products.append({
                'id': f"{store_name}_{product_id}",
                'title': title,
                'url': link,
                'store': store_name,
            })
        for child in value.values():
            products.extend(extract_products(child, store_name, default_url))
    return products


def check_json_search(store_name, url, headers, default_url, method="GET", body=None):
    if not url:
        print(f"Skipping {store_name}: search URL is not configured.")
        return []
    if not headers:
        print(f"Skipping {store_name}: headers are not configured.")
        return []

    print(f"Checking {store_name}...")
    try:
        if method == "POST":
            response = requests.post(url, headers=headers, json=body or {}, timeout=15)
        else:
            response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return extract_products(response.json(), store_name, default_url)
    except (requests.RequestException, ValueError) as error:
        print(f"Error scraping {store_name}: {error}")
        return []


def check_blinkit():
    return check_json_search(
        "Blinkit",
        "https://blinkit.com/v1/layout/search?q=hot+wheels",
        BLINKIT_HEADERS,
        "https://blinkit.com",
        method="POST",
    )


def check_zepto():
    return check_json_search(
        "Zepto", ZEPTO_SEARCH_URL, ZEPTO_HEADERS, "https://www.zeptonow.com", ZEPTO_METHOD, ZEPTO_BODY
    )


def check_instamart():
    return check_json_search(
        "Instamart",
        INSTAMART_SEARCH_URL,
        INSTAMART_HEADERS,
        "https://www.swiggy.com/instamart",
        INSTAMART_METHOD,
        INSTAMART_BODY,
    )

def main():
    seen_products = load_seen_products()
    all_current_drops = []
    
    # Check each quick-commerce provider for current Hot Wheels listings.
    all_current_drops.extend(check_blinkit())
    all_current_drops.extend(check_zepto())
    all_current_drops.extend(check_instamart())
    
    # 3. Filter and Alert
    new_discoveries = []
    for drop in all_current_drops:
        if drop['id'] not in seen_products:
            new_discoveries.append(drop)
            
    if new_discoveries:
        print(f"Found {len(new_discoveries)} new items!")
        # Telegram has a limit on message length; if too many, we loop
        sent_ids = []
        for i in range(0, len(new_discoveries), 5):
            chunk = new_discoveries[i:i+5]
            message = "🚗 <b>NEW HOT WHEELS DROP!</b> 🚗\n\n"
            for d in chunk:
                message += f"🏪 <b>{escape(d['store'])}</b>\n"
                message += f"📦 {escape(d['title'])}\n"
                message += f"🔗 <a href=\"{escape(d['url'], quote=True)}\">View Product</a>\n\n"
            if not send_telegram_alert(message):
                break
            sent_ids.extend(drop['id'] for drop in chunk)

        if sent_ids:
            seen_products.update(sent_ids)
            save_seen_products(seen_products)
    else:
        print("No new items found.")

if __name__ == "__main__":
    main()
