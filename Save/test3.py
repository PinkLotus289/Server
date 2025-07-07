#!/usr/bin/env python3
import json
import random
import httpx
import sys
from pathlib import Path
from bs4 import BeautifulSoup

PROXY_USER = "spz49ysjcr"
PROXY_PASS = "jB3fl2=arzsTd3OK8m"
PROXY_HOST = "pl.decodo.com"
PROXY_PORT = 20000
PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"

def random_ipv4():
    return ".".join(str(random.randint(1, 255)) for _ in range(4))

def get_session():
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; fetch_lot_data/1.0)",
        "X-Forwarded-For": random_ipv4(),
    }
    transport = httpx.HTTPTransport(proxy=PROXY_URL, retries=1)
    return httpx.Client(transport=transport, headers=headers, timeout=20.0)

def fetch_html(stock_id: str, out_path: Path):
    url = f"https://www.iaai.com/VehicleDetail/{stock_id}~US"
    with get_session() as client:
        html = client.get(url)
        html.raise_for_status()
        out_path.write_text(html.text, encoding="utf-8")
        ip = client.get("https://api64.ipify.org?format=text").text.strip()
        return ip

def fetch_ajax_data(salvage_id: str):
    url = f"https://vis.iaai.com/Home/GetVehicleData?salvageId={salvage_id}"
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "X-Forwarded-For": random_ipv4(),
    }
    with get_session() as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

def parse_html(path: Path) -> dict:
    soup = BeautifulSoup(path.read_text("utf-8"), "html.parser")
    result = {}

    labels = [
        "Stock #", "Selling Branch", "VIN (Status)", "Loss", "Primary Damage",
        "Title/Sale Doc", "Title/Sale Doc Brand", "Start Code", "Key",
        "Odometer", "Airbags", "Vehicle", "Body Style", "Engine",
        "Transmission", "Drive Line Type", "Fuel Type", "Cylinders",
        "Restraint System", "Exterior/Interior", "Options", "Manufactured In",
        "Vehicle Class", "Model", "Series",
        "Vehicle Location", "Auction Date and Time", "Lane/Run #", "Aisle/Stall",
        "Actual Cash Value", "Estimated Repair Cost", "Seller",
    ]

    for label in labels:
        span = soup.find("span", class_="data-list__label", string=lambda t: t and t.strip().startswith(label))
        if span:
            val = span.find_next_sibling("span", class_="data-list__value")
            result[label] = val.get_text(strip=True) if val else None
        else:
            result[label] = None

    # Фото с resizer
    resizer_photos = []
    for img in soup.select("img[src*='resizer?imageKeys=']"):
        src = img.get("src")
        if src and src.startswith("https://vis.iaai.com/resizer"):
            resizer_photos.append(src)

    # Фото с ThreeSixty
    # Пример ссылки: /ThreeSixtyImageRetriever?tenant=iaai&partitionKey=43063024&imageOrder=1
    partition_id = None
    for script in soup.find_all("script"):
        if script.string and "partitionKey" in script.string:
            if "partitionKey=" in script.string:
                idx = script.string.find("partitionKey=")
                partition_id = script.string[idx:].split("&")[0].split("=")[1]
                break

    photos_360 = []
    if partition_id:
        for i in range(1, 21):  # обычно до 20 фото
            url = f"https://mediaretriever.iaai.com/ThreeSixtyImageRetriever?tenant=iaai&partitionKey={partition_id}&imageOrder={i}"
            photos_360.append(url)

    result["photos"] = resizer_photos + photos_360
    return result

def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_lot_data.py <stock_number>", file=sys.stderr)
        sys.exit(1)

    stock_id = sys.argv[1]
    html_path = Path("vehicle.html")
    json_path = Path("vehicle_full.json")

    print("🔄 Fetching lot HTML page…")
    ip = fetch_html(stock_id, html_path)
    print(f"🌐 Used IP: {ip}")
    print(f"💾 Saved HTML to: {html_path}")

    print("📦 Parsing lot data from HTML…")
    parsed = parse_html(html_path)

    print("📡 Fetching full VIN via AJAX…")
    try:
        ajax = fetch_ajax_data(stock_id)
        parsed["Full VIN"] = ajax.get("Vin")
        parsed["Make"] = ajax.get("MakeName")
        parsed["Model"] = ajax.get("ModelName")
        parsed["Year"] = ajax.get("ModelYear")
    except Exception as e:
        print("⚠️ Failed to fetch AJAX data:", e)

    json_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ JSON saved to: {json_path}")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
