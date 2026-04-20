import os
import json
import requests

# --- CONFIGURATION ---
# Telegram Settings (Set these in GitHub Secrets)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# State File to remember what we've already alerted you about
STATE_FILE = "seen_products.json"

# Quick Commerce Headers (Extract these from browser Network tab)
BLINKIT_HEADERS = json.loads(os.environ.get("BLINKIT_HEADERS", "{}"))
ZEPTO_HEADERS = json.loads(os.environ.get("ZEPTO_HEADERS", "{}"))

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
        json.dump(list(seen_set), f)

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing. Printing to console instead:")
        print(message)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

# --- SHOPIFY SCRAPERS (Toycra, KrazyCaterpillar) ---
def check_shopify_store(store_name, base_url, collection_path="hot-wheels"):
    """Scrapes Shopify stores using their hidden JSON endpoint."""
    print(f"Checking {store_name}...")
    url = f"{base_url}/collections/{collection_path}/products.json?limit=250"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    new_drops = []
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        products = res.json().get('products', [])
        
        for p in products:
            available = any(variant.get('available', False) for variant in p.get('variants', []))
            if available:
                item_id = f"{store_name}_{p['id']}"
                title = p['title']
                link = f"{base_url}/products/{p['handle']}"
                new_drops.append({'id': item_id, 'title': title, 'url': link, 'store': store_name})
    except Exception as e:
        print(f"Error scraping {store_name}: {e}")
    return new_drops

# --- QUICK COMMERCE SCRAPERS ---
def check_blinkit():
    """Scrapes Blinkit using the v1/layout/search endpoint."""
    print("Checking Blinkit...")
    if not BLINKIT_HEADERS:
        print("Skipping Blinkit: No headers provided in secrets.")
        return []

    # Using the path you provided
    url = "https://blinkit.com/v1/layout/search?q=hot+wheels"
    
    # Based on your copy-paste, content-length was 0, meaning it's an empty POST body
    payload = {} 
    
    new_drops = []
    try:
        res = requests.post(url, headers=BLINKIT_HEADERS, json=payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            # Blinkit Layout API returns widgets. We look for 'product_card' snippets.
            widgets = data.get('data', {}).get('widgets', [])
            for widget in widgets:
                objects = widget.get('data', {}).get('objects', [])
                for obj in objects:
                    # Check if it's a product and has inventory
                    if 'product_id' in obj or 'id' in obj:
                        title = obj.get('name', 'Hot Wheels Car')
                        # Only add if it's actually a Hot Wheels product (filtering noise)
                        if "hot wheels" in title.lower():
                            inventory = obj.get('inventory', 0)
                            if inventory > 0:
                                p_id = obj.get('product_id', obj.get('id'))
                                item_id = f"Blinkit_{p_id}"
                                link = f"https://blinkit.com/prn/x/{p_id}"
                                new_drops.append({
                                    'id': item_id, 
                                    'title': title, 
                                    'url': link, 
                                    'store': 'Blinkit'
                                })
    except Exception as e:
         print(f"Error scraping Blinkit: {e}")
    return new_drops

def main():
    seen_products = load_seen_products()
    all_current_drops = []
    
    # 1. Check Shopify Stores
    all_current_drops.extend(check_shopify_store("KrazyCaterpillar", "https://krazycaterpillar.com"))
    all_current_drops.extend(check_shopify_store("Toycra", "https://toycra.com"))
    
    # 2. Check Quick Commerce
    all_current_drops.extend(check_blinkit())
    
    # 3. Filter and Alert
    new_discoveries = []
    for drop in all_current_drops:
        if drop['id'] not in seen_products:
            new_discoveries.append(drop)
            seen_products.add(drop['id'])
            
    if new_discoveries:
        print(f"Found {len(new_discoveries)} new items!")
        # Telegram has a limit on message length; if too many, we loop
        for i in range(0, len(new_discoveries), 5):
            chunk = new_discoveries[i:i+5]
            message = "🚗 <b>NEW HOT WHEELS DROP!</b> 🚗\n\n"
            for d in chunk:
                message += f"🏪 <b>{d['store']}</b>\n"
                message += f"📦 {d['title']}\n"
                message += f"🔗 <a href='{d['url']}'>View Product</a>\n\n"
            send_telegram_alert(message)
        
        save_seen_products(seen_products)
    else:
        print("No new items found.")

if __name__ == "__main__":
    main()
