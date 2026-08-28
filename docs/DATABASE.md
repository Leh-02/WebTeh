# TopBearing — структура бази даних

Основна БД для production — PostgreSQL. SQLite використовується лише як zero-config локальний режим.

```mermaid
erDiagram
    USERS ||--o{ ORDERS : places
    CATEGORIES ||--o{ PRODUCTS : contains
    BRANDS ||--o{ PRODUCTS : manufactures
    PRODUCTS ||--o| BEARING_SPECS : has
    PRODUCTS ||--o| BELT_SPECS : has
    PRODUCTS ||--o| SEAL_SPECS : has
    ORDERS ||--|{ ORDER_ITEMS : contains
    PRODUCTS o|--o{ ORDER_ITEMS : referenced_by
    USERS o|--o{ AUDIT_LOGS : creates

    USERS {
      int id PK
      string email UK
      string password_hash
      string role
      bool is_active
    }
    CATEGORIES {
      int id PK
      string code UK
      bool require_prepayment_default
      bool cod_allowed_default
    }
    BRANDS {
      int id PK
      string name UK
      string slug UK
    }
    PRODUCTS {
      int id PK
      string sku UK
      string slug UK
      int category_id FK
      int brand_id FK
      numeric price
      int stock_qty
      bool require_prepayment_override nullable
      bool cod_allowed_override nullable
      bool is_active
    }
    BEARING_SPECS {
      int product_id PK_FK
      string subtype
      numeric inner_diameter_mm
      numeric outer_diameter_mm
      numeric width_mm
      int rows
      string cage_type
      string seal_type
      string clearance
      string precision_class
    }
    BELT_SPECS {
      int product_id PK_FK
      string belt_type
      string profile
      numeric length_mm
      numeric width_mm
    }
    SEAL_SPECS {
      int product_id PK_FK
      string seal_type
      numeric inner_diameter_mm
      numeric outer_diameter_mm
      numeric width_mm
      string material
      string lip_type
    }
    ORDERS {
      int id PK
      string number UK
      int user_id FK nullable
      string status
      string payment_status
      numeric subtotal
      numeric delivery_price
      numeric total
    }
    ORDER_ITEMS {
      int id PK
      int order_id FK
      int product_id FK nullable
      string sku_snapshot
      string name_snapshot
      int qty
      numeric unit_price
      numeric line_total
    }
```

## Чому характеристики винесені в окремі таблиці

Підшипник, ремінь і сальник мають різні поля. Зберігання всього в одному JSON ускладнило б індекси, валідацію і діапазонний пошук. Тому `products` містить спільні комерційні поля, а `bearing_specs`, `belt_specs`, `seal_specs` — технічні.

## Правила оплати

1. `categories.require_prepayment_default` та `categories.cod_allowed_default` задають правило категорії.
2. `products.require_prepayment_override` і `products.cod_allowed_override` можуть бути `NULL` (успадкувати), `true` або `false`.
3. Якщо хоча б одна позиція кошика вимагає передоплату, накладений платіж для всього замовлення не пропонується.
4. `store_settings.cod_enabled` та `store_settings.cod_min_total` задають глобальні обмеження.

Це дозволяє, наприклад, зробити сальники передоплатними за замовчуванням, але окрему дорогу позицію дозволити відправляти післяплатою.

## Залишки та історія

Товар не видаляється фізично з `products` при натисканні «Видалити» в адмінці — він стає неактивним. Це зберігає історію, посилання `order_items.product_id` і аудит. Крім того, `order_items` зберігає snapshot SKU, назви й ціни на момент продажу.

Checkout використовує row lock (`SELECT ... FOR UPDATE`) у PostgreSQL перед списанням залишків. При скасуванні замовлення кількість повертається на склад.
