# Price Monitor

Личный сервис для наблюдения за ценами на карточки товаров. Страница публикуется через GitHub Pages, а вся запись данных выполняется через GitHub Actions.

## Как устроено

- `index.html`, `styles.css`, `app.js` - статический интерфейс таблицы цен.
- `data/products.json` - список отслеживаемых карточек.
- `data/prices.json` - история наблюдений.
- `scripts/add_product.py` - добавление товара и первый замер цены.
- `scripts/update_prices.py` - плановое обновление цен.
- `.github/workflows/add-product.yml` - ручное добавление товара по ссылке.
- `.github/workflows/update-prices.yml` - обновление цен в 00:01, 09:01 и 20:00 МСК, плюс ручной запуск.
- `.github/workflows/pages.yml` - публикация статической страницы на GitHub Pages.

## Добавление товара

На сайте кнопка `Добавить` открывает workflow `Add product`. Вставьте ссылку в поле `product_url` и нажмите `Run workflow`. Workflow добавит карточку в `data/products.json`, сделает первый замер и закоммитит изменения.

Это обходится без отдельного backend и без секретов в браузере. Прямой POST из GitHub Pages в репозиторий без внешнего backend невозможен безопасно: для записи нужен токен, а его нельзя хранить в публичном фронтенде.

## Ручное обновление цен

Кнопка `Обновить цены` открывает workflow `Update prices`, который можно запустить вручную. По расписанию он запускается автоматически:

- 00:01 МСК
- 09:01 МСК
- 20:00 МСК

## Поддерживаемые площадки

Плановый Python-обновлятор определяет площадку по ссылке:

- Wildberries: публичный card API по артикулу из URL.
- Ozon: встроенные JSON/meta-данные страницы и общий fallback.
- Яндекс Маркет: встроенные JSON/meta-данные страницы и общий fallback.
- AliExpress: встроенные JSON/meta-данные страницы и общий fallback.

## Локальная проверка

```bash
python3 -m http.server 8765
```

Откройте `http://127.0.0.1:8765/`.

Проверить обновлятор без записи:

```bash
python3 scripts/update_prices.py --dry-run
```

Проверить добавление товара локально:

```bash
python3 scripts/add_product.py "https://www.wildberries.ru/catalog/768952004/detail.aspx"
```

## GitHub Pages

Страница публикуется по адресу:

`https://alati-elle.github.io/price-mon/`
