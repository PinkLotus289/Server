# api.py

import os
import sys
import json
import signal
from pathlib import Path
from typing import List, Optional
from subprocess import Popen, PIPE

from fastapi import FastAPI, Query, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from vehicle_view import view as car_view_func
from fastapi.responses import JSONResponse


# КОНСТАНТЫ
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "JSONs"
LOG_DIR  = BASE_DIR / "parser" / "logs"
PROJECT_ROOT = Path(__file__).parent.resolve()

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

@app.get("/cars", response_model=List[Car])
def list_cars(
    limit: int = Query(100, gt=0, le=1000),
    lastId: int = Query(0, ge=0),
):
    filtered = [c for c in _all_cars if c["lot_id"] > lastId]
    return filtered[:limit]

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

