# Price Monitor

Минимальная версия личного сервиса для наблюдения за ценами. Страница работает на GitHub Pages, а история цен хранится в JSON-файлах репозитория.

## Как устроено

- `index.html`, `styles.css`, `app.js` - статический интерфейс.
- `data/products.json` - список отслеживаемых карточек.
- `data/prices.json` - история наблюдений.
- `scripts/update_prices.py` - обновление цен.
- `.github/workflows/update-prices.yml` - запуск обновления в 08:00, 14:00 и 20:00 UTC.

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

В настройках репозитория включите Pages:

1. `Settings` -> `Pages`.
2. Source: `Deploy from a branch`.
3. Branch: `main`, folder: `/root`.

После публикации страница будет доступна по адресу вида:

`https://alati-elle.github.io/price-mon/`
