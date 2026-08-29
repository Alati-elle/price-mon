# Price Monitor

Личный сервис для наблюдения за ценами на карточки товаров. Интерфейс остаётся статическим и публикуется через GitHub Pages, а добавление товаров выполняет отдельный backend API.

## Как устроено

- `index.html`, `styles.css`, `app.js` - статический интерфейс таблицы цен.
- `config.js` - адрес backend API для фронтенда.
- `data/products.json` - список отслеживаемых карточек.
- `data/prices.json` - история наблюдений.
- `scripts/update_prices.py` - плановое обновление цен.
- `worker/price-mon-worker.js` - backend API для добавления товара.
- `.github/workflows/update-prices.yml` - запуск обновления в 00:01, 09:01 и 20:00 МСК.
- `.github/workflows/deploy-worker.yml` - деплой Cloudflare Worker API.
- `.github/workflows/pages.yml` - публикация статической страницы на GitHub Pages.

## Backend API

Фронтенд добавляет товар через `POST /api/products`.

Worker проверяет `Authorization: Bearer <ADMIN_TOKEN>`, валидирует ссылку, добавляет товар в `data/products.json`, делает первый замер для Wildberries через card API и атомарно коммитит `data/products.json` + `data/prices.json` через GitHub API.

Для деплоя Worker нужны GitHub Secrets:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

И Cloudflare Worker secrets:

- `GITHUB_TOKEN` - GitHub token с правом писать в репозиторий.
- `ADMIN_TOKEN` - личный ключ для формы добавления товара.

После деплоя Worker укажите его адрес в `config.js`:

```js
window.PRICE_MON_API_BASE = "https://price-mon-api.<account>.workers.dev";
```

## Поддерживаемые площадки

Плановый Python-обновлятор определяет площадку по ссылке:

- Wildberries: публичный card API по артикулу из URL.
- Ozon: встроенные JSON/meta-данные страницы и общий fallback.
- Яндекс Маркет: встроенные JSON/meta-данные страницы и общий fallback.
- AliExpress: встроенные JSON/meta-данные страницы и общий fallback.

Worker при добавлении сразу делает первый замер для Wildberries. Для остальных площадок товар сохраняется, а цена подтягивается плановым обновлением.

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

Страница публикуется по адресу:

`https://alati-elle.github.io/price-mon/`
