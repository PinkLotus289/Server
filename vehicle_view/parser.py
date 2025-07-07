import re
import json
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup

def parse_html(path: Path) -> dict:
    """
    Вытаскивает из vehicle.html все текстовые поля по лейблам
    data-list__label → data-list__value, аукционную дату и Start Code.
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
        # найти точный <span class="data-list__label">Label:</span>
        lbl = soup.find(
            lambda t:
                t.name == "span"
                and t.get("class") and "data-list__label" in t.get("class")
                and t.get_text(strip=True).startswith(f"{label}:")
        )
        if not lbl:
            result[label] = None
            continue

        # потом — следующий sibling с class data-list__value
        val = None
        for sib in lbl.next_siblings:
            if getattr(sib, "get", None) and "data-list__value" in (sib.get("class") or []):
                text = sib.get_text(" ", strip=True)
                if label == "Auction Date and Time":
                    # уберём лишние переводы строк
                    text = " ".join(text.split())
                val = text or None
                break

        result[label] = val

    # если Start Code так и не нашли — смотрим в скрытых input/span
    if result.get("Start Code") is None:
        nov = soup.find("span", id="startcodeengine_novideo")
        hid = soup.find("input", id="hdnrunAndDrive_Ind")
        if nov:
            result["Start Code"] = nov.get_text(strip=True)
        elif hid and hid.get("value"):
            result["Start Code"] = hid["value"]

    # тянем partitionKey для 360°
    pk = None
    for sc in soup.find_all("script"):
        txt = sc.string or ""
        m = re.search(r"partitionKey\s*:\s*'(\d+)'", txt)
        if m:
            pk = m.group(1)
            break
    result["_partitionKey360"] = pk

    return result

def extract_photos_from_dimensions(html_path: Path) -> list[str]:
    """
    В JSON.parse('…') ищет блок dimensions.keys и генерирует по каждому
    ключу ссылку через resizer с width=1000&height=300.
    Плюс до 20 360°-картинок.
    """
    text = html_path.read_text("utf-8")
    soup = BeautifulSoup(text, "html.parser")
    m = re.search(r"JSON\.parse\('(.+?)'\)", text, re.S)
    if not m:
        return []
    dims = json.loads(m.group(1))
    host = "https://vis.iaai.com"
    photos = []
    for e in dims.get("keys", []):
        k = e.get("k")
        if k:
            photos.append(
                f"{host}/resizer?imageKeys={urllib.parse.quote(k, safe='')}"
                f"&width=1000&height=300"
            )

    # 360°
    if dims.get("image360Ind") and dims.get("image360Url"):
        qm = re.search(r"partitionKey=([^&']+)", dims["image360Url"])
        if qm:
            pk = qm.group(1)
            for i in range(1, 21):
                photos.append(
                    f"https://mediaretriever.iaai.com/ThreeSixtyImageRetriever"
                    f"?tenant=iaai&partitionKey={pk}&imageOrder={i}"
                )

    return list(dict.fromkeys(photos))

def collect_photos(detail_json: dict, partition_key: str, html_path: Path) -> list[str]:
    """
    Собирает:
      1) все URL из detail_json["Images"] / ["BusinessImages"]
      2) до 20 ссылок на 360°
      3) ссылки из dimensions-блока
    """
    photos = []
    for img in detail_json.get("Images", []) + detail_json.get("BusinessImages", []):
        for k in ("LargeUrl", "MediumUrl", "SmallUrl"):
            url = img.get(k)
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
