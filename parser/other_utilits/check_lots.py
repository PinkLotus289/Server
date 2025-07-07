import json
from collections import Counter

FILE = "parser/JSONs/bmw_lots.json"

try:
    with open(FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception as e:
    print(f"❌ Ошибка загрузки {FILE}: {e}")
    exit(1)

lot_ids = [lot.get("lot_id", "N/A") for lot in data if lot.get("lot_id")]
lot_count = len(lot_ids)

# Подсчёт повторяющихся lot_id
counter = Counter(lot_ids)
duplicates = [lot_id for lot_id, count in counter.items() if count > 1]

print(f"📦 Всего лотов: {lot_count}")
print(f"🔁 Повторяющихся lot_id: {len(duplicates)}")

if duplicates:
    print("📋 Повторы:")
    for dup in duplicates:
        print(f" - {dup} (встречается {counter[dup]} раз)")
else:
    print("✅ Повторов не найдено.")
