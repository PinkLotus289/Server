# parser/fetcher.py

import os
import math
import tempfile
import shutil
import random

import httpx
from bs4 import BeautifulSoup

from seleniumwire.undetected_chromedriver.v2 import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .utils import random_xff

# ——————————————————————————————————————————
# Residential proxy credentials
PROXY_USER = "spz49ysjcr"
PROXY_PASS = "jB3fl2=arzsTd3OK8m"
PROXY_HOST = "pl.decodo.com"
# ——————————————————————————————————————————


class IaaIFetcher:
    def __init__(self, keyword: str, page_size: int = 100, proxy_port: int = 20001):
        self.keyword = keyword
        self.page_size = page_size
        self.proxy_port = proxy_port
        self.cookies = None
        self.user_agent = None
        self.max_page = None

    def start_session(self) -> int:
        """
        1) Создаём уникальный user-data-dir для каждого fetcher-а
        2) Конфигурируем ChromeOptions
        3) Подключаем selenium-wire с прокси URL, включающим логин/пароль
        4) Собираем cookies, UA и считаем общее число страниц
        """
        # 1) Уникальный каталог профиля
        profile_dir = os.path.join(
            tempfile.gettempdir(),
            f"udc_profile_{self.keyword}_{self.proxy_port}"
        )
        if os.path.exists(profile_dir):
            shutil.rmtree(profile_dir)

        profile_dir = tempfile.mkdtemp(prefix=f"udc_profile_{self.keyword}_{self.proxy_port}_")

        # 2) Опции Chrome
        opts = ChromeOptions()
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--allow-insecure-localhost")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--window-size=1920,1080")
        # НЕ headless — чтобы вручную решить капчу при необходимости
        opts.add_argument(f"--user-data-dir={profile_dir}")

        # 3) selenium-wire прокси с учётками в URL
        proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{self.proxy_port}"
        seleniumwire_options = {
            "proxy": {
                "http":  proxy_url,
                "https": proxy_url,
            }
        }

        driver = Chrome(version_main=137, options=opts, seleniumwire_options=seleniumwire_options)

        # 4) Проверяем внешний IP через прокси
        driver.get("https://api64.ipify.org?format=text")
        print("🌐 Browser IP:", driver.find_element(By.TAG_NAME, "body").text)

        # 5) Открываем первую страницу и ждём появления лотов
        url = f"https://www.iaai.com/Search?Keyword={self.keyword}"
        driver.get(url)
        WebDriverWait(driver, 120).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.table-cell--data.p-0"))
        )

        # 6) Подсчитываем общее число лотов и страниц
        soup = BeautifulSoup(driver.page_source, "html.parser")
        header = soup.select_one("#headerTotalAmount")
        total = int(header.text.replace(",", "")) if header else 0
        self.max_page = math.ceil(total / self.page_size)
        print(f"🔢 Found {total} items → {self.max_page} pages")

        # 7) Сохраняем cookies и User-Agent
        self.cookies = driver.get_cookies()
        self.user_agent = driver.execute_script("return navigator.userAgent;")

        driver.quit()

        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass

        return self.max_page

    def build_client(self) -> httpx.Client:
        """
        Создаёт httpx.Client:
        - прокси передаём через HTTPTransport(proxy=URL)
        - сохраняем cookies и User-Agent из браузера
        """
        jar = httpx.Cookies()
        for ck in self.cookies:
            jar.set(ck["name"], ck["value"], domain=ck.get("domain"), path=ck.get("path"))

        proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{self.proxy_port}"
        transport = httpx.HTTPTransport(proxy=proxy_url, retries=1)
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

        return httpx.Client(
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Referer": f"https://www.iaai.com/Search?Keyword={self.keyword}",
                "Origin": "https://www.iaai.com",
            },
            cookies=jar,
            transport=transport,
            timeout=timeout,
        )

    def fetch_page(self, client: httpx.Client, page: int) -> str:
        """
        Загружает HTML страницы через POST-запрос.
        """
        payload = {
            "Searches": [{"Facets": None, "FullSearch": self.keyword, "LongRanges": None}],
            "ZipCode": "",
            "miles": 0,
            "PageSize": self.page_size,
            "CurrentPage": page,
            "BidStatusFilters": [{"BidStatus": 6, "IsSelected": True}],
            "SaleStatusFilters": [{"SaleStatus": 1, "IsSelected": True}],
            "ShowRecommendations": False,
            "Sort": [{"IsGeoSort": False, "SortField": "AuctionDateTime", "IsDescending": False}],
        }
        client.headers["X-Forwarded-For"] = random_xff()
        resp = client.post("https://www.iaai.com/Search", json=payload)
        return resp.text
