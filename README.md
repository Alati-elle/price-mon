# Price Monitor

Минимальная версия личного сервиса для наблюдения за ценами. Страница работает на GitHub Pages, а история цен хранится в JSON-файлах репозитория.

## Как устроено

- `index.html`, `styles.css`, `app.js` - статический интерфейс.
- `data/products.json` - список отслеживаемых карточек.
- `data/prices.json` - история наблюдений.
- `scripts/update_prices.py` - обновление цен.
- `.github/workflows/update-prices.yml` - запуск обновления в 00:01, 09:01 и 20:00 МСК.
- `.github/workflows/pages.yml` - публикация статической страницы на GitHub Pages.

## Поддерживаемые площадки

Скрипт автоматически определяет площадку по ссылке:

- Wildberries: чтение через публичный card API по артикулу из URL.
- Ozon: поиск цены во встроенных JSON/meta-данных страницы, затем общий fallback.
- Яндекс Маркет: поиск цены во встроенных JSON/meta-данных страницы, затем общий fallback.
- AliExpress: поиск цены во встроенных JSON/meta-данных страницы, затем общий fallback.

Некоторые площадки могут блокировать запросы GitHub Actions или отдавать цену только после JavaScript-рендера. Для таких карточек в следующих версиях стоит добавить Playwright или отдельные API-адаптеры.

## Добавление товара

Пока сохранение через интерфейс не пишет в GitHub. Для MVP добавьте запись в `data/products.json`:

```json
{
  "id": "unique-product-id",
  "title": "Название товара",
  "url": "https://example.com/product",
  "store": "example.com",
  "currency": "RUB",
  "active": true
}
```

Поле `marketplace` можно не указывать: скрипт сам определит `wildberries`, `ozon`, `yandex_market`, `aliexpress` или `generic`.

После commit workflow начнет собирать цену по расписанию. Демо-товар в репозитории оставлен неактивным, чтобы первый scheduled run не записывал ожидаемую ошибку по `example.com`.

## Локальная проверка

```bash
python3 -m http.server 8765
```

Откройте `http://127.0.0.1:8765/`.

Проверить обновлятор без записи:

```bash
python3 scripts/update_prices.py --dry-run
```

## GitHub Pages

В репозитории добавлен workflow деплоя Pages через GitHub Actions. Если Pages еще не активировался автоматически, включите его в настройках:

1. `Settings` -> `Pages`.
2. Source: `GitHub Actions`.

После публикации страница будет доступна по адресу:

`https://alati-elle.github.io/price-mon/`
