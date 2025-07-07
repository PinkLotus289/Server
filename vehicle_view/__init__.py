import re
from pathlib import Path

from .fetcher import fetch_html, fetch_vehicle_ajax, fetch_detail_api
from .parser import parse_html, collect_photos

def view(url: str) -> dict:
    """
    Точка входа: принимает либо чистый stock_id, либо полный URL
    типа https://www.iaai.com/VehicleDetail/43076760~US
    и возвращает словарь с полной инфой по лоту.
    """
    # извлечь ID из урла, если передали полный линк
    m = re.search(r'/VehicleDetail/(\d+)', url)
    stock_id = m.group(1) if m else url

    # 1) скачать HTML
    html_path = Path(f"/tmp/vehicle_{stock_id}.html")
    fetch_html(stock_id, html_path)

    # 2) распарсить все поля из HTML
    data = parse_html(html_path)

    # 3) достать полную VIN-ку и базовые поля через AJAX
    try:
        ajax = fetch_vehicle_ajax(stock_id)
        data["Full VIN"]   = ajax.get("Vin")
        data["Make"]       = ajax.get("MakeName")
        data["ModelName"]  = ajax.get("ModelName")
        data["ModelYear"]  = ajax.get("ModelYear")
    except Exception:
        # если не удалось — пропускаем
        pass

    # 4) скрытый detail-API для всех остальных полей + массива изображений
    try:
        detail = fetch_detail_api(stock_id)
    except Exception:
        detail = {}

    # 5) собрать все фотки
    pk = data.pop("_partitionKey360", None)
    data["photos"] = collect_photos(detail, pk, html_path)

    return data
