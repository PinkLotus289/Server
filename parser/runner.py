import os
import json
import time
import logging
import tempfile
import multiprocessing as mp
from multiprocessing import Process, Queue

from httpx import ProxyError
from urllib3.exceptions import ProtocolError
from selenium.common.exceptions import NoSuchWindowException

from .fetcher import IaaIFetcher
from .parser import parse_items
from .utils import sleep_random

# Папка для логов внутри parser/
BASE_DIR = os.path.dirname(__file__)
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def ready_flag_path(keyword: str) -> str:
    """Путь к временного флагу готовности секции."""
    return os.path.join(tempfile.gettempdir(), f"parser_ready_{keyword}")

def setup_logger(keyword: str) -> logging.Logger:
    logger = logging.getLogger(keyword)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        fh = logging.FileHandler(os.path.join(LOG_DIR, f"{keyword}.log"), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

def process_section(
    keyword: str,
    proxy_port: int,
    output_dir: str,
    start_page: int,
    page_size: int,
    logger: logging.Logger
) -> int:
    fetcher = IaaIFetcher(keyword, page_size=page_size, proxy_port=proxy_port)
    dyn_pages = fetcher.start_session()
    logger.info(f"Динамическое число страниц: {dyn_pages}")

    # ставим флаг готовности сразу после закрытия браузера
    open(ready_flag_path(keyword), "w").close()

    client = fetcher.build_client()
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{keyword}_lots.json")

    # загружаем уже собранное, если есть
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                all_items = json.load(f)
        except json.JSONDecodeError:
            all_items = []
    else:
        all_items = []

    for page in range(start_page, dyn_pages + 1):
        logger.info(f"Запрос страницы {page}/{dyn_pages}")
        html = fetcher.fetch_page(client, page)

        if "captcha" in html.lower() or "incapsula" in html.lower():
            logger.warning(f"Капча на странице {page}, перезапуск сессии")
            raise RuntimeError("Captcha detected")

        items = parse_items(html)
        logger.info(f"Страница {page}: найдено {len(items)} лотов")
        all_items.extend(items)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_items, f, ensure_ascii=False, indent=2)
        logger.info(f"Сохранено {len(all_items)} лотов → {output_path}")

        sleep_random(2, 5)

    logger.info(f"🎉 Все страницы ({dyn_pages}) обработаны.")
    return dyn_pages

def run_section_with_restart(
    keyword: str,
    proxy_port: int,
    output_dir: str,
    page_size: int,
    max_retries: int = 5
) -> str:
    logger = setup_logger(keyword)
    output_path = os.path.join(output_dir, f"{keyword}_lots.json")

    # определяем стартовую страницу
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                current = json.load(f)
            done_pages = len(current) // page_size
            start_page = done_pages + 1
            logger.info(f"Найден существующий файл, старт с {start_page}")
        except json.JSONDecodeError:
            start_page = 1
            logger.warning(f"Файл {output_path} битый, стартуем с 1")
    else:
        start_page = 1

    attempts = 0
    while True:
        try:
            process_section(keyword, proxy_port, output_dir, start_page, page_size, logger)
            break

        except ProxyError as e:
            logger.error(f"ProxyError на разделе «{keyword}»: {e}")
            logger.error("Прокси требует аутентификацию — прекращаем.")
            break

        except (ProtocolError, NoSuchWindowException) as e:
            attempts += 1
            logger.error(f"{type(e).__name__} на разделе «{keyword}»: {e}")
            if attempts >= max_retries:
                logger.error(f"Превышено {max_retries} попыток перезапуска для «{keyword}», выходим.")
                break
            logger.info(f"Попытка {attempts}/{max_retries} после сбоя, рестарт через 5 сек")
            time.sleep(5)
            continue

        except Exception as e:
            attempts += 1
            logger.exception(f"Сбой на странице {start_page}: {e}")
            if attempts >= max_retries:
                logger.error(f"Превышено {max_retries} попыток перезапуска для «{keyword}», выходим.")
                break
            # пересчёт текущей страницы
            if os.path.exists(output_path):
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        current = json.load(f)
                    done_pages = len(current) // page_size if current else 0
                    start_page = done_pages + 1
                except json.JSONDecodeError:
                    start_page = 1
            else:
                start_page = 1
            logger.info(f"Попытка {attempts}/{max_retries}. Рестарт с {start_page} через 5 сек")
            time.sleep(5)

    return output_path

def worker(keyword: str, proxy_port: int, output_dir: str, page_size: int, queue: Queue):
    try:
        result = run_section_with_restart(keyword, proxy_port, output_dir, page_size)
        queue.put(result)
    except Exception as e:
        setup_logger(keyword).exception(f"Фатальный сбой раздела: {e}")

def main():
    mp.set_start_method("spawn", force=True)

    cfg_path = os.path.join(BASE_DIR, "sections.json")
    cfg = json.load(open(cfg_path, "r", encoding="utf-8"))
    sections   = cfg.get("sections", [])
    output_dir = cfg.get("output_dir", "JSONs")
    page_size  = cfg.get("page_size", 100)

    queue = Queue()
    processes = []

    for idx, sec in enumerate(sections):
        keyword, port = sec["keyword"], sec["proxy_port"]
        p = Process(target=worker,
                    args=(keyword, port, output_dir, page_size, queue),
                    name=keyword)
        p.start()
        setup_logger(keyword).info(f"Started process pid={p.pid}")

        # ждём флаг готовности и даём ещё 120с
        flag = ready_flag_path(keyword)
        setup_logger(keyword).info("Waiting for browser init…")
        while not os.path.exists(flag):
            time.sleep(1)
        os.remove(flag)
        if idx < len(sections) - 1:
            setup_logger(keyword).info("Browser init done — sleeping 120s before next")
            time.sleep(60)

        processes.append(p)

    for p in processes:
        p.join()
        setup_logger(p.name).info(f"Process {p.name} pid={p.pid} exited with code={p.exitcode}")

    # собираем результаты
    results = []
    while not queue.empty():
        results.append(queue.get())

    print("Все задачи завершены. Файлы:")
    for r in results:
        print(" ", r)

if __name__ == "__main__":
    main()
