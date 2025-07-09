from bs4 import BeautifulSoup

def parse_items(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.table-cell--data.p-0")
    items = []

    for card in cards:
        a = card.find("a")
        if not a:
            continue
        row = card.find_parent("div", class_="table-row-inner")

        def get_span(key: str) -> str:
            tag = row.find("span", title=lambda t: t and key in t)
            return tag.text.strip() if tag else "N/A"

        title = a.text.strip()
        link = "https://www.iaai.com" + a["href"]
        vin = get_span("Please log in as a buyer")

        # новое извлечение lot_id
        stock_el = row.select_one(
            "ul.data-list--search li.data-list__item "
            "span.data-list__value[title^='Stock #:']"
        )
        lot_id = stock_el.text.strip() if stock_el else "N/A"

        preview = (row.find("img") or {}).get("data-src", "N/A")
        auc_date = (row.find("div", class_="table-cell-horizontal-center") or {}).get_text(strip=True)

        items.append({
            "title": title,
            "link": link,
            "lot_id": lot_id,
            "vin": vin,
            "preview": preview,
            "odometer": get_span("Odometer"),
            "damage": get_span("Primary Damage"),
            "run_and_drive": get_span("Run & Drive"),
            "airbags": get_span("Airbags"),
            "key": get_span("Key"),
            "engine": get_span("Engine"),
            "fuel_type": get_span("Fuel Type"),
            "cylinders": get_span("Cylinder"),
            "branch": get_span("Branch"),
            "country": get_span("Country"),
            "acv": get_span("ACV"),
            "auction_date": auc_date,
        })

    return items
