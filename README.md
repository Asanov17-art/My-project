# aliexpress-affiliate

Python-клиент для **AliExpress Affiliate API** (AliExpress Open Platform / Portals):
поиск товаров, генерация партнёрских ссылок, категории, акции и отчёты по заказам.

Без «магии»: один слой подписывает и отправляет запросы, второй даёт типизированные
методы. Вся логика покрыта тестами, которые не ходят в сеть.

## Что нужно перед началом

1. Аккаунт в партнёрской программе AliExpress (Portals) и **tracking id**.
2. Приложение на [AliExpress Open Platform](https://openservice.aliexpress.com) —
   оттуда берутся `App Key` и `App Secret`.
3. Подключённый (одобренный) пакет API **Affiliate** для этого приложения.
   Без него гейтвей отвечает `ApiError` с `sub_code=isv.permission-deny`.

```bash
cp .env.example .env    # и вписать свои ключи
pip install -r requirements.txt
```

## Быстрый старт

```python
from aliexpress_affiliate import AffiliateClient

client = AffiliateClient.from_env(target_currency="USD", ship_to_country="KZ")

page = client.search_products("wireless earbuds", page_size=10, sort="LAST_VOLUME_DESC")
print(page.total_record_count, "товаров найдено")

for product in page:
    print(product.title, product.sale_price, product.currency, product.orders)

link = client.generate_link("https://www.aliexpress.com/item/1005001.html")
print(link.promotion_link)
```

Постраничный обход с ограничителями (чтобы случайно не выжечь квоту):

```python
for product in client.iter_products("led strip", max_items=200):
    ...
```

Отчёт по заказам за период:

```python
from datetime import datetime, timedelta, timezone

end = datetime.now(timezone.utc)
start = end - timedelta(days=30)

for order in client.iter_orders(start, end):
    print(order.order_id, order.order_status, order.estimated_paid_commission)
```

## CLI

```bash
export PYTHONPATH=src            # или pip install -e .
python -m aliexpress_affiliate.cli --env-file .env search "phone case" --page-size 5
python -m aliexpress_affiliate.cli link https://www.aliexpress.com/item/1005001.html
python -m aliexpress_affiliate.cli categories
python -m aliexpress_affiliate.cli orders --days 30 --json
```

После `pip install -e .` то же самое доступно как команда `aliexpress`.

## Что реализовано

| Метод клиента | API AliExpress |
| --- | --- |
| `search_products` / `iter_products` | `aliexpress.affiliate.product.query` |
| `hot_products` | `aliexpress.affiliate.hotproduct.query` |
| `download_hot_products` | `aliexpress.affiliate.hotproduct.download` |
| `product_details` | `aliexpress.affiliate.productdetail.get` |
| `generate_links` / `generate_link` | `aliexpress.affiliate.link.generate` |
| `categories` | `aliexpress.affiliate.category.get` |
| `featured_promos` | `aliexpress.affiliate.featuredpromo.get` |
| `featured_promo_products` | `aliexpress.affiliate.featuredpromo.products.get` |
| `orders` | `aliexpress.affiliate.order.list` |
| `orders_by_index` / `iter_orders` | `aliexpress.affiliate.order.listbyindex` |
| `order_details` | `aliexpress.affiliate.order.get` |

## Как устроено

- `signing.py` — подпись запроса. По умолчанию `sha256` (HMAC-SHA256 от строки
  `key+value`, отсортированной по ключу); поддержан и легаси-`md5`
  (`MD5(secret + строка + secret)`). Пустые значения выбрасываются до подписи —
  именно их рассинхрон чаще всего даёт `isv.sign-check-failure`.
- `client.py` — `TopClient`: системные параметры, таймстемп, повторы с
  экспоненциальной задержкой (троттлинг `code=7`, 5xx, обрывы связи) и разбор
  двух конвертов ошибок платформы.
- `models.py` — разбор ответов. Гейтвей возвращает коллекции в трёх разных
  формах (`{"products": {"product": [...]}}`, `{"products": [...]}`, одиночный
  объект без обёртки) — `unpack_list` понимает все. Исходный JSON всегда лежит
  в `raw`, так что новые поля API доступны и без обновления пакета.
- `affiliate.py` — прикладные методы, значения по умолчанию (`tracking_id`,
  валюта, язык, страна доставки) и клиентская проверка лимитов (50 id или
  ссылок на вызов) — чтобы не тратить квоту на заведомо отбойные запросы.

Ошибки: `ApiError` (платформа: подпись, права, метод), `RateLimitError`
(квота — ретраится автоматически), `BusinessError` (`resp_code != 200`),
`TransportError` (сеть), `ConfigurationError` (ключи и аргументы).

## Настройки

| Переменная | Назначение |
| --- | --- |
| `ALIEXPRESS_APP_KEY` | App Key приложения |
| `ALIEXPRESS_APP_SECRET` | App Secret приложения |
| `ALIEXPRESS_TRACKING_ID` | tracking id партнёрского кабинета |
| `ALIEXPRESS_GATEWAY` | адрес гейтвея (по умолчанию `https://api-sg.aliexpress.com/sync`) |
| `ALIEXPRESS_SIGN_METHOD` | `sha256` (по умолчанию) или `md5` |
| `ALIEXPRESS_TIMEOUT` | таймаут HTTP-запроса в секундах |

Легаси-гейтвей `https://gw.api.taobao.com/router/rest` тоже поддержан — он
требует другого формата времени и участия пути в подписи:

```python
from aliexpress_affiliate import ClientConfig, AffiliateClient

config = ClientConfig(
    app_key="...", app_secret="...",
    gateway="https://gw.api.taobao.com/router/rest",
    timestamp_style="datetime",
    api_path="/router/rest",
)
client = AffiliateClient(config, tracking_id="...")
```

## Тесты

```bash
pip install pytest
python -m pytest
```

53 теста, сети не требуют: HTTP заменён на `FakeTransport`, который записывает
отправленные payload'ы и отдаёт заранее подготовленные ответы. Проверяются
подпись (обе схемы), системные параметры, ретраи, оба конверта ошибок,
пагинация, курсорный обход заказов и все формы коллекций в ответах.

## Ограничения

- Пакет говорит с **официальным API** и требует одобренного приложения;
  парсинга страниц aliexpress.com здесь нет и не планируется.
- Реальные вызовы из среды Claude Code на web заблокированы сетевой политикой
  окружения (`connect_rejected` на `api-sg.aliexpress.com`). Запускайте локально
  либо добавьте домен в allowlist окружения.
- Все временные метки методов заказов гейтвей трактует в GMT+8; `format_order_time`
  переводит `datetime` с таймзоной автоматически, наивные — берёт как есть.
