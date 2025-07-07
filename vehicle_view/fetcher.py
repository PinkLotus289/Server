import random
import httpx
from pathlib import Path

# ——————————————————————————————————————————
# Residential proxy settings (pl.decodo.com ports 20001–20010)
PROXY_USER = "spz49ysjcr"
PROXY_PASS = "jB3fl2=arzsTd3OK8m"
PROXY_HOST = "gate.decodo.com"
PROXY_PORT = 10000
PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
# ——————————————————————————————————————————

def random_ipv4() -> str:
    return ".".join(str(random.randint(1, 255)) for _ in range(4))

def get_client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; iaai-lot-parser/1.0)",
            "X-Forwarded-For": random_ipv4()
        },
        transport=httpx.HTTPTransport(proxy=PROXY_URL, retries=1),
        timeout=20.0
    )

def fetch_html(stock_id: str, out_path: Path) -> str:
    """Скачивает страницу лота и сохраняет в файл, возвращает внешний IP."""
    url = f"https://www.iaai.com/VehicleDetail/{stock_id}~US"
    with get_client() as client:
        try:
            ip = client.get("https://api64.ipify.org?format=text").text.strip()
        except Exception:
            ip = "unknown"
        r = client.get(url)
        r.raise_for_status()
        out_path.write_text(r.text, encoding="utf-8")
    return ip

def fetch_vehicle_ajax(salvage_id: str) -> dict:
    """Получает полный VIN и базовые поля через AJAX."""
    url = f"https://vis.iaai.com/Home/GetVehicleData?salvageId={salvage_id}"
    with get_client() as client:
        r = client.get(url, headers={"X-Requested-With":"XMLHttpRequest"})
        r.raise_for_status()
        return r.json()

def fetch_detail_api(stock_id: str) -> dict:
    """Тайный API /api/Search/GetDetailPageData для всех полей + массива изображений."""
    url = "https://www.iaai.com/api/Search/GetDetailPageData"
    with get_client() as client:
        r = client.get(url, params={"stockNumber": stock_id})
        r.raise_for_status()
        return r.json()
