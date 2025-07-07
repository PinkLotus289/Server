import os
import json
import time
import logging
from multiprocessing import Process, Queue

from httpx import ProxyError

from .fetcher import IaaIFetcher
from .parser import parse_items
from .utils import sleep_random

# Папка для логов внутри parser/
BASE_DIR = os.path.dirname(__file__)
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


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

    client = fetcher.build_client()

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{keyword}_lots.json")

    # загружаем уже собранное, если есть
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            all_items = json.load(f)
    else:
        all_items = []

    for page in range(start_page, dyn_pages + 1):
        logger.info(f"Запрос страницы {page}/{dyn_pages}")
        html = fetcher.fetch_page(client, page)

        # ==== новая логика при капче ====
        if "captcha" in html.lower() or "incapsula" in html.lower():
            logger.warning(f"Капча/блокировка на странице {page}, перезапуск сессии")
            # бросаем ошибку, чтобы run_section_with_restart перезапустил сессию
            raise RuntimeError("Captcha detected")
        # =================================

        items = parse_items(html)
        logger.info(f"Страница {page}: найдено {len(items)} лотов")
        all_items.extend(items)

        # сохраняем прогресс
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

    # готовим стартовую страницу
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            current = json.load(f)
        done_pages = len(current) // page_size
        start_page = done_pages + 1
        logger.info(f"Найден существующий файл, старт с {start_page}")
    else:
        start_page = 1

    attempts = 0
    while True:
        try:
            process_section(
                keyword,
                proxy_port,
                output_dir,
                start_page,
                page_size,
                logger
            )
            # если дошли до конца без исключений — выходим
            break

        except ProxyError as e:
            logger.error(f"ProxyError на разделе «{keyword}»: {e}")
            logger.error("Прокси требует аутентификацию — прекращаем.")
            break

        except Exception as e:
            attempts += 1
            logger.exception(f"Сбой на странице {start_page}: {e}")

            if attempts >= max_retries:
                logger.error(f"Превышено {max_retries} попыток перезапуска для «{keyword}», выходим.")
                break

            # пересчитываем start_page по уже сохранённому прогрессу
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    current = json.load(f)
                done_pages = len(current) // page_size if current else 0
                start_page = done_pages + 1
            else:
                start_page = 1

            logger.info(f"Попытка {attempts}/{max_retries}. Рестарт с страницы {start_page} через 5 сек")
            time.sleep(5)

    return output_path



def worker(keyword: str, proxy_port: int, output_dir: str, page_size: int, queue: Queue):
    """
    Запускает секцию и кладёт результат (путь к JSON) в очередь.
    """
    try:
        result = run_section_with_restart(keyword, proxy_port, output_dir, page_size)
        queue.put(result)
    except Exception as e:
        setup_logger(keyword).exception(f"Фатальный сбой раздела: {e}")


def main():
    cfg_path = os.path.join(BASE_DIR, "sections.json")
    cfg = json.load(open(cfg_path, "r", encoding="utf-8"))
    sections   = cfg.get("sections", [])
    output_dir = cfg.get("output_dir", "JSONs")
    page_size  = cfg.get("page_size", 100)

    # очередь для сбора результатов
    queue = Queue()
    processes = []

    # стартуем процесс на каждый раздел
    for sec in sections:
        p = Process(
            target=worker,
            args=(sec["keyword"], sec["proxy_port"], output_dir, page_size, queue),
            name=sec["keyword"]
        )
        p.start()
        setup_logger(sec["keyword"]).info(f"Started process pid={p.pid}")
        processes.append(p)

    # ждём пока все завершатся
    for p in processes:
        p.join()
        setup_logger(p.name).info(f"Process {p.name} pid={p.pid} exited with code={p.exitcode}")

    # собираем пути из очереди
    results = []
    while not queue.empty():
        results.append(queue.get())

    print("Все задачи завершены. Файлы:")
    for path in results:
        print(" ", path)


if __name__ == "__main__":
    main()
