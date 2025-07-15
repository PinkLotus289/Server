# api.py
import difflib
import os
import sys
import json
import signal
import requests
from pathlib import Path
from typing import List, Optional, Dict
from subprocess import Popen, PIPE

from fastapi import FastAPI, Query, HTTPException, status, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, conlist
from vehicle_view import view as car_view_func
from fastapi.responses import JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler


# КОНСТАНТЫ
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "JSONs"
LOG_DIR  = BASE_DIR / "parser" / "logs"
PROJECT_ROOT = Path(__file__).parent.resolve()
SECTIONS_PATH = PROJECT_ROOT / "parser" / "sections.json"
DATA_FILE = os.path.join(os.path.dirname(__file__), "JSONs", "Automobiles_lots.json")

parser_proc = None

# Модель Car
class Car(BaseModel):
    lot_id: int
    title: str
    link: str
    vin: str
    preview: str
    odometer: str
    damage: str
    run_and_drive: str
    airbags: str
    key: str
    engine: str
    fuel_type: str
    cylinders: str
    branch: str
    country: str
    acv: str
    auction_date: str

# Загрузка всех лотов в память
_all_cars: List[dict] = []
for fn in os.listdir(DATA_DIR):
    if fn.endswith("_lots.json"):
        with open(DATA_DIR / fn, encoding="utf-8") as f:
            for item in json.load(f):
                try:    item["lot_id"] = int(item.get("lot_id", 0))
                except: item["lot_id"] = 0
                _all_cars.append(item)
_all_cars.sort(key=lambda x: x["lot_id"])

app = FastAPI(
    title="IAAI Cars API",
    description="Keyset-pagination + управление парсером и логами",
    version="1.0.0"
)

# Глобальная переменная для хранения процесса парсинга
parser_proc: Optional[Popen] = None


sched = BackgroundScheduler()

def scheduled_run():
    # сначала чистим JSON-файлы
    try:
        requests.post("http://127.0.0.1:8000/admin/clear-jsons", timeout=10)
    except Exception as e:
        # если что-то пошло не так — залогируем или просто проигнорируем
        print("⛔ Не удалось очистить JSONs:", e)

    # потом запускаем парсер
    try:
        requests.post("http://127.0.0.1:8000/admin/run-parser", timeout=10)
    except Exception as e:
        print("⛔ Не удалось запустить парсер:", e)

# повесить задачу на каждый день в 8:30
sched.add_job(
    scheduled_run,
    trigger="cron",
    hour=8,
    minute=30,
    timezone="Europe/Moscow"  # поставьте вашу зону
)
sched.start()

@app.on_event("shutdown")
def shutdown_scheduler():
    sched.shutdown()

@app.get("/cars", response_model=List[Dict])
async def get_cars(
    limit:       int,
    lastStock:   Optional[str] = Query(None, alias="lastStock",
                         description="stock# последнего лота предыдущей страницы"),
    brand:       Optional[str] = Query(None, description="опциональная фильтрация по марке")
):
    # 1) Загружаем весь список
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)

    # 2) Фильтруем по ключевому слову в title, если указали brand
    if brand:
        br = brand.strip().lower()
        filtered = [
            it for it in items
            if br in it.get("title", "").lower()
        ]
        if not filtered:
            raise HTTPException(404, f"Нет лотов с «{brand}» в title")
        items = filtered

    # 3) Ищем позицию lastStock
    if lastStock:
        idx = next(
            (i for i, it in enumerate(items) if str(it.get("stock#")) == lastStock),
            None
        )
        if idx is None:
            raise HTTPException(400, f"lastStock={lastStock} не найден в результирующем списке")
        start = idx + 1
    else:
        start = 0

    # 4) Берём срез limit штук
    slice_ = items[start : start + limit]
    return slice_

@app.post("/admin/run-parser", status_code=status.HTTP_202_ACCEPTED)
def run_parser():
    global parser_proc
    if parser_proc and parser_proc.poll() is None:
        raise HTTPException(409, "Parser is already running")

    # Убеждаемся, что у нас есть папка parser
    if not (PROJECT_ROOT / "parser").is_dir():
        raise HTTPException(500, "Directory 'parser' not found")

    # Запускаем как пакет
    cmd = [
        sys.executable,
        "-u",                  # немедленный вывод (unbuffered)
        "-m", "parser.runner"  # запускаем модуль parser.runner
    ]
    try:
        parser_proc = Popen(
            cmd,
            cwd=str(PROJECT_ROOT),  # <--- project root
            preexec_fn=os.setsid    # для группы процессов
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to start parser: {e}")

    return {
        "status": "started",
        "pid": parser_proc.pid,
        "cmd": cmd,
        "cwd": str(PROJECT_ROOT)
    }

@app.post("/admin/stop-parser", status_code=status.HTTP_200_OK)
def stop_parser():
    global parser_proc
    if not parser_proc or parser_proc.poll() is not None:
        raise HTTPException(400, "No running parser to stop")
    try:
        pg = os.getpgid(parser_proc.pid)
        os.killpg(pg, signal.SIGTERM)
        parser_proc.wait(5)
    except Exception as e:
        raise HTTPException(500, f"Error stopping parser: {e}")
    finally:
        parser_proc = None
    return {"status": "stopped"}

@app.get("/admin/parser-status", status_code=status.HTTP_200_OK)
def parser_status():
    """
    Опциональный endpoint, чтобы узнать, жив ли процесс.
    """
    if parser_proc and parser_proc.poll() is None:
        return {"running": True, "pid": parser_proc.pid}
    return {"running": False}

@app.post("/admin/clear-logs")
def clear_logs():
    if not LOG_DIR.exists():
        raise HTTPException(404, f"Log dir not found: {LOG_DIR}")
    deleted = []
    for lf in LOG_DIR.glob("*.log"):
        lf.unlink(missing_ok=True)
        deleted.append(lf.name)
    return {"status": "logs cleared", "deleted": deleted}

@app.get("/admin/logs/{log_name}")
def download_log(log_name: str):
    file_path = LOG_DIR / log_name
    if not file_path.exists() or file_path.parent != LOG_DIR:
        raise HTTPException(404, "Log file not found")
    return FileResponse(path=file_path, media_type="text/plain", filename=log_name)

@app.get("/car/view")
def car_view(url: str = Query(..., description="Полная ссылка на лот, например https://www.iaai.com/VehicleDetail/43076760~US")):
    """
    Возвращает полную карточку автомобиля по ссылке или по просто переданному stock_id.
    """
    try:
        data = car_view_func(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch vehicle data: {e}")
    return JSONResponse(content=data)

@app.delete("/admin/clear-jsons", status_code=200)
def delete_all_jsons():
    """
    Удаляет все JSON-файлы в папке JSONs.
    """
    json_dir = PROJECT_ROOT / "JSONs"
    if not json_dir.is_dir():
        raise HTTPException(status_code=500, detail=f"Directory not found: {json_dir}")

    deleted = []
    for file_path in json_dir.glob("*.json"):
        try:
            file_path.unlink()
            deleted.append(file_path.name)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete {file_path.name}: {e}"
            )

    return {"status": "deleted", "files": deleted}


@app.delete("/admin/clear-json/{name}", status_code=200)
def delete_single_json(name: str):
    """
    Удаляет указанный JSON-файл из папки JSONs.
    Параметр name указывается без расширения .json.
    """
    json_dir = PROJECT_ROOT / "JSONs"
    if not json_dir.is_dir():
        raise HTTPException(status_code=500, detail=f"Directory not found: {json_dir}")

    filename = f"{name}.json"
    file_path = json_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    try:
        file_path.unlink()  # полное удаление файла
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {e}")

    return {"status": "deleted", "file": filename}


class Section(BaseModel):
    keyword: str = Field(
        ...,
        description="Ключевое слово раздела",
        example="BMW"
    )
    proxy_port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Порт прокси для раздела",
        example=20001
    )

class SectionsConfig(BaseModel):
    sections: List[Section] = Field(
        ...,
        min_items=1,
        description="Список разделов (минимум один)"
    )
    output_dir: str = Field(
        "JSONs",
        description="Папка для вывода JSON-файлов"
    )
    page_size: int = Field(
        100,
        ge=1,
        description="Размер страницы (число лотов за запрос)"
    )

def read_config() -> SectionsConfig:
    try:
        raw = SECTIONS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        return SectionsConfig.model_validate(data)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="sections.json не найден")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения конфигурации: {e}")

def write_config(cfg: SectionsConfig):
    try:
        SECTIONS_PATH.write_text(
            json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить sections.json: {e}")

@app.get(
    "/admin/sections",
    response_model=SectionsConfig,
    summary="Получить текущие разделы"
)
def get_sections():
    """
    Возвращает весь файл parser/sections.json.
    """
    return read_config()

@app.post(
    "/admin/section",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить или обновить один раздел"
)
def add_or_update_section(
    section: Section = Body(..., description="Новая конфигурация раздела")
):
    """
    Если раздел с таким keyword есть — обновляем proxy_port,
    иначе — добавляем его в список.
    """
    cfg = read_config()
    # ищем существующий
    for idx, sec in enumerate(cfg.sections):
        if sec.keyword == section.keyword:
            cfg.sections[idx].proxy_port = section.proxy_port
            break
    else:
        cfg.sections.append(section)

    write_config(cfg)
    return {"status": "ok", "section": section}

@app.delete(
    "/admin/section/{keyword}",
    status_code=200,
    summary="Надёжно удалить раздел по keyword"
)
def delete_section(keyword: str):
    """
    Удаляет раздел с указанным keyword (игнорируя регистр и пробелы).
    Если точного совпадения нет, предлагает похожие варианты.
    """
    cfg = read_config()
    # нормализуем вход
    key_norm = keyword.strip().lower()
    # список всех существующих ключей
    existing = [sec.keyword for sec in cfg.sections]
    # ищем точное совпадение без учёта регистра
    to_delete = [sec for sec in cfg.sections if sec.keyword.lower() == key_norm]

    if not to_delete:
        # никаких точных совпадений — попробуем найти похожие
        suggestions = difflib.get_close_matches(
            keyword,
            existing,
            n=3,
            cutoff=0.5
        )
        if suggestions:
            detail = (
                f"Раздел '{keyword}' не найден. "
                f"Возможно, вы имели в виду: {', '.join(suggestions)}"
            )
        else:
            detail = (
                f"Раздел '{keyword}' не найден. "
                f"Доступные разделы: {', '.join(existing)}"
            )
        raise HTTPException(status_code=404, detail=detail)

    # удаляем все совпавшие (обычно один)
    cfg.sections = [
        sec for sec in cfg.sections
        if sec.keyword.lower() != key_norm
    ]
    write_config(cfg)
    return {"status": "deleted", "keyword": to_delete[0].keyword}