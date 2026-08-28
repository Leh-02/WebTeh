# TopBearing

Повний серверний e-commerce MVP для продажу підшипників, пасових ременів, сальників/манжет та суміжних промислових комплектуючих.

## Реалізовано

- біло-синій мінімалістичний адаптивний інтерфейс;
- головна сторінка, каталог, товар, кошик, checkout;
- пошук за назвою/SKU + технічні фільтри;
- підшипники: підтип, кількість рядів, сепаратор, внутрішній/зовнішній діаметр;
- ремені: профіль та діапазон довжини;
- сальники: матеріал та діапазони діаметрів;
- клієнтська реєстрація, вхід, історія замовлень;
- один `/login` для клієнта й адміністратора, але доступ до `/admin` дає лише серверна роль `admin`;
- адмін-панель: товари, фото, характеристики, залишки, ціни, активація/деактивація;
- замовлення: статус замовлення та статус оплати;
- правила передоплати/накладеного платежу на рівні категорії й окремого товару;
- керування способами доставки;
- CSRF для змінюючих запитів, HTTP security headers, PBKDF2-SHA256 паролі, server-side role checks;
- audit log критичних адмін-дій;
- PostgreSQL для production, SQLite для швидкого локального запуску;
- Docker Compose.

## Найшвидший запуск без Docker

У каталозі проєкту:

```bash
python -m pip install -r requirements.txt
python seed.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Потім відкрийте `http://127.0.0.1:8000`.

На Windows можна запустити `run_local.bat`.

### Dev admin

За замовчуванням `seed.py` створює:

- email: `admin@topbearing.local`
- password: `ChangeMe123!`

Перед реальним розгортанням задайте `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SESSION_SECRET` через environment і ввімкніть `COOKIE_SECURE=1` за HTTPS.

## Docker / PostgreSQL

```bash
docker compose up --build
```

Web: `http://localhost:8000`.

Для реального сервера створіть `.env` на базі `.env.example` і замініть усі секрети.

## Оплата

Поточний проєкт повністю реалізує **policy/workflow** оплати: передоплата або накладений платіж залежно від кошика. Реальний acquiring (Monobank/LiqPay/WayForPay) потребує merchant credentials і callback URL, тому в цей архів не вшиті чужі/фіктивні ключі. Точка інтеграції — після створення `Order` із `payment_method=prepaid`; callback має оновити `payment_status=paid`.

## Доставка

Нова пошта та самовивіз уже є як керовані способи доставки. Реальний API Нової пошти для автопідбору міста/відділення потребує API key; без нього checkout приймає місто та номер відділення текстом.

## Зображення

Адмін може вставити URL або завантажити JPG/PNG/WEBP до 5 МБ. Локально файли потрапляють у `static/uploads`. У production рекомендовано замінити storage на S3/R2.

## База даних

Детальна схема та логіка: [`docs/DATABASE.md`](docs/DATABASE.md).

## Структура

```text
app/
  main.py                 routes, auth, cart, checkout, admin
  models.py               SQLAlchemy schema
  security.py             password hashing/session user lookup
  services/
    catalog.py            catalog query/filter engine
    payment_policy.py     COD/prepayment rules
templates/
  admin/                   admin UI
  ...                      storefront UI
static/
  css/app.css
  js/app.js
  img/
  uploads/
docs/DATABASE.md
seed.py
Dockerfile
docker-compose.yml
```

## Що варто додати перед production launch

- merchant acquiring API + signed webhook verification;
- Nova Poshta API/autocomplete;
- email/SMS/Telegram повідомлення;
- object storage + image resizing;
- reverse proxy (Caddy/Nginx), HTTPS, rate limiting і backups;
- Alembic migrations та CI/CD;
- інтеграцію з вашою обліковою системою/залишками замість ручного stock management.

## Масовий імпорт товарів

Для перенесення структурованих позицій зі старої системи додано `scripts/import_products_csv.py`. Він робить upsert по SKU, створює відсутні бренди та записує технічні характеристики у правильну таблицю категорії. Формат колонок описаний у коментарі на початку скрипта.
