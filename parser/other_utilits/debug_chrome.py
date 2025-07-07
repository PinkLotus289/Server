# debug_chrome_selenium.py

import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

print("1) Импорт готов")

# === Настройки Chrome ===
options = Options()
# НЕ headless — чтобы вы видели окно и могли нажать F12
# Отключаем некоторые флаги автоматизации, но без экзотики
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1280,800")

# Явно указываем путь к вашему установленному Chrome (по необходимости)
# options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

print("2) Устанавливаем Chromedriver через webdriver_manager…", flush=True)
service = Service(ChromeDriverManager().install())

print("3) Запускаем ChromeDriver…", flush=True)
driver = webdriver.Chrome(service=service, options=options)

print("4) Открываем нужный URL…", flush=True)
driver.get("https://www.iaai.com/VehicleDetail/42645191~US")

print("🧪 Окно открыто! Скорее нажмите F12 и поработайте в DevTools.\nЖду 5 минут…", flush=True)
time.sleep(3600)  # 5 минут

print("5) Закрываем браузер…", flush=True)
driver.quit()
print("6) Готово.", flush=True)
