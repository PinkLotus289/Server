import re
from pathlib import Path

from .fetcher import fetch_html, fetch_vehicle_ajax, fetch_detail_api
from .parser import parse_html, collect_photos

def view(url: str) -> dict:
    """
    Принимает либо чистый stock_id, либо полный URL
    типа https://www.iaai.com/VehicleDetail/43076760~US
    и возвращает словарь с полной инфой по лоту,
    включая lot_id (из HTML) и stock# (из URL).
    """
    # ——————————————
    # 1) достаём stock# из URL
    m = re.search(r'/VehicleDetail/(\d+)', url)
    stock_id = m.group(1) if m else url

    # 2) скачиваем HTML
    html_path = Path(f"/tmp/vehicle_{stock_id}.html")
    fetch_html(stock_id, html_path)

    # 3) парсим всю табличную информацию
    data = parse_html(html_path)

    # переименуем и вынесем stock# и lot_id
    #  - stock# = то, что было в URL
    data["stock#"] = stock_id
    #  - lot_id = то, что извлекли из самой страницы (label "Stock #")
    lot_from_html = data.pop("Stock #", None)
    # если в парсере не нашли — можно взять из detail API или из ajax
    data["lot_id"] = lot_from_html

    # 4) подтягиваем AJAX-данные
    try:
        ajax = fetch_vehicle_ajax(stock_id)
        data["Full VIN"]   = ajax.get("Vin")
        data["Make"]       = ajax.get("MakeName")
        data["ModelName"]  = ajax.get("ModelName")
        data["ModelYear"]  = ajax.get("ModelYear")
    except Exception:
        pass

    # 5) detail-API + фотки
    try:
        detail = fetch_detail_api(stock_id)
    except Exception:
        detail = {}
    pk = data.pop("_partitionKey360", None)
    data["photos"] = collect_photos(detail, pk, html_path)

    return data