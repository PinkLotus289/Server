#!/usr/bin/env python3
import json
import random
import httpx
import sys
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup

# ——————————————————————————————————————————
# Residential proxy settings (pl.decodo.com ports 20001–20010)
PROXY_USER = "spz49ysjcr"
PROXY_PASS = "jB3fl2=arzsTd3OK8m"
PROXY_HOST = "pl.decodo.com"
PROXY_PORT = 20000
PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
# ——————————————————————————————————————————

def random_ipv4() -> str:
    return ".".join(str(random.randint(1, 255)) for _ in range(4))

def get_client() -> httpx.Client:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; iaai-lot-parser/1.0)",
        "X-Forwarded-For": random_ipv4(),
    }
    transport = httpx.HTTPTransport(proxy=PROXY_URL, retries=1)
    return httpx.Client(transport=transport, headers=headers, timeout=20.0)

def fetch_html(stock_id: str, out_path: Path) -> str:
    """
    Скачиваем страницу лота и сохраняем в out_path.
    Возвращаем внешний IP.
    """
    url = f"https://www.iaai.com/VehicleDetail/{stock_id}~US"
    with get_client() as client:
        try:
            ip = client.get("https://api64.ipify.org?format=text").text.strip()
        except Exception:
            ip = "unknown"
        r = client.get(url); r.raise_for_status()
        out_path.write_text(r.text, encoding="utf-8")
    return ip

def fetch_vehicle_ajax(salvage_id: str) -> dict:
    """
    AJAX-запрос /Home/GetVehicleData для полного VIN и базовых полей.
    """
    url = f"https://vis.iaai.com/Home/GetVehicleData?salvageId={salvage_id}"
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "X-Forwarded-For": random_ipv4(),
    }
    with get_client() as client:
        r = client.get(url, headers=headers); r.raise_for_status()
        return r.json()

def fetch_detail_api(stock_id: str) -> dict:
    """
    Скрытый API /api/Search/GetDetailPageData
    возвращает все поля лота + массив картинок.
    """
    url = "https://www.iaai.com/api/Search/GetDetailPageData"
    params = {"stockNumber": stock_id}
    with get_client() as client:
        r = client.get(url, params=params); r.raise_for_status()
        return r.json()

def parse_html(path: Path) -> dict:
    """
    Парсим vehicle.html и вытаскиваем все текстовые поля по лейблам
    data-list__label → data-list__value, включая Start Code.
    Auction Date and Time теперь нормализуется в одну строку без лишних переносов.
    """
    soup = BeautifulSoup(path.read_text("utf-8"), "html.parser")
    result = {}

    labels = [
        "Stock #", "Selling Branch", "VIN (Status)", "Loss", "Primary Damage",
        "Title/Sale Doc", "Start Code", "Key", "Odometer", "Airbags",
        "Vehicle", "Body Style", "Engine", "Transmission",
        "Drive Line Type", "Fuel Type", "Cylinders", "Restraint System",
        "Exterior/Interior", "Options", "Manufactured In",
        "Vehicle Class", "Model",
        "Vehicle Location", "Auction Date and Time", "Lane/Run #",
        "Aisle/Stall", "Actual Cash Value", "Estimated Repair Cost", "Seller",
    ]

    for label in labels:
        lbl = soup.find(
            lambda tag:
                tag.name == "span"
                and tag.get("class")
                and "data-list__label" in tag.get("class")
                and tag.get_text(strip=True).startswith(f"{label}:")
        )
        if not lbl:
            result[label] = None
            continue

        val = None
        for sib in lbl.next_siblings:
            if not hasattr(sib, "get"):
                continue
            if "data-list__value" in (sib.get("class") or []):
                text = sib.get_text(" ", strip=True)
                if label == "Auction Date and Time":
                    text = " ".join(text.split())
                val = text or None
                break

        result[label] = val

    # если не нашли Start Code — дёрнем из скрытого <input>
    if result.get("Start Code") is None:
        hid = soup.find("input", id="hdnrunAndDrive_Ind")
        novideo = soup.find("span", id="startcodeengine_novideo")
        if novideo:
            result["Start Code"] = novideo.get_text(strip=True)
        elif hid and hid.get("value"):
            result["Start Code"] = hid["value"]

    # для 360° ключа
    pk = None
    for script in soup.find_all("script"):
        txt = script.string or ""
        m = re.search(r"partitionKey\s*:\s*'(\d+)'", txt)
        if m:
            pk = m.group(1)
            break
    result["_partitionKey360"] = pk

    return result

def extract_photos_from_dimensions(html_path: Path) -> list[str]:
    """
    Ищем JSON.parse('…') с полем "keys":[…] и генерируем ссылки через resizer
    с фиксированными width=1000&height=300, плюс 360°-картинки.
    """
    text = html_path.read_text("utf-8")
    soup = BeautifulSoup(text, "html.parser")

    pattern = re.compile(r"JSON\.parse\('(.+?)'\)", re.S)
    raw = None
    for tag in soup.find_all("script"):
        scr = tag.string or ""
        if "dimensions" in scr and "JSON.parse" in scr:
            m = pattern.search(scr)
            if m:
                raw = m.group(1)
                break
    if not raw:
        return []

    dims = json.loads(raw)
    host = "https://vis.iaai.com"
    photos = []
    for entry in dims.get("keys", []):
        k = entry.get("k")
        if not k:
            continue
        photos.append(f"{host}/resizer?imageKeys={urllib.parse.quote(k, safe='')}&width=1000&height=300")

    if dims.get("image360Ind") and dims.get("image360Url"):
        pm = re.search(r"partitionKey=([^&']+)", dims["image360Url"])
        if pm:
            pk = pm.group(1)
            for i in range(1, 21):
                photos.append(
                    f"https://mediaretriever.iaai.com/ThreeSixtyImageRetriever"
                    f"?tenant=iaai&partitionKey={pk}&imageOrder={i}"
                )

    return list(dict.fromkeys(photos))

def collect_photos(detail_json: dict, partition_key: str, html_path: Path) -> list[str]:
    photos = []

    imgs = detail_json.get("Images") or detail_json.get("BusinessImages") or []
    for img in imgs:
        for key in ("LargeUrl","MediumUrl","SmallUrl"):
            url = img.get(key)
            if url and url.startswith("http"):
                photos.append(url)

    if partition_key:
        for i in range(1, 21):
            photos.append(
                f"https://mediaretriever.iaai.com/ThreeSixtyImageRetriever"
                f"?tenant=iaai&partitionKey={partition_key}&imageOrder={i}"
            )

    photos.extend(extract_photos_from_dimensions(html_path))
    return list(dict.fromkeys(photos))

def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_lot_full.py <stockNumber|URL>", file=sys.stderr)
        sys.exit(1)

    arg = sys.argv[1]
    # Если передали URL вида https://.../VehicleDetail/43076760~US, извлекаем ID
    m = re.search(r'/VehicleDetail/(\d+)', arg)
    stock_id = m.group(1) if m else arg

    html_path = Path("vehicle.html")
    json_path = Path(f"{stock_id}_full.json")

    print("🔄 Fetching HTML page…")
    ip = fetch_html(stock_id, html_path)
    print(f"🌐 Used IP: {ip}")

    print("📦 Parsing HTML…")
    parsed = parse_html(html_path)

    print("📡 Fetching AJAX data (full VIN)…")
    try:
        ajax = fetch_vehicle_ajax(stock_id)
        parsed["Full VIN"]   = ajax.get("Vin")
        parsed["Make"]       = ajax.get("MakeName")
        parsed["ModelName"]  = ajax.get("ModelName")
        parsed["ModelYear"]  = ajax.get("ModelYear")
    except Exception as e:
        print("⚠️ AJAX error:", e, file=sys.stderr)

    print("📡 Fetching detail API data…")
    try:
        detail = fetch_detail_api(stock_id)
    except Exception as e:
        print("⚠️ Detail API error:", e, file=sys.stderr)
        detail = {}

    print("📷 Collecting photos…")
    pk = parsed.pop("_partitionKey360", None)
    parsed["photos"] = collect_photos(detail, pk, html_path)

    json_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Saved full JSON to {json_path}")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
