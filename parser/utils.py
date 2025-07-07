import random
import time

def random_xff() -> str:
    """Генерирует рандомный X-Forwarded-For IP."""
    return ".".join(str(random.randint(1, 255)) for _ in range(4))

def sleep_random(a: float = 2.0, b: float = 5.0) -> None:
    """Случайная пауза между запросами."""
    time.sleep(random.uniform(a, b))
