from __future__ import annotations

import html
import os
import re
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload
from starlette.middleware.sessions import SessionMiddleware

from .database import SessionLocal, get_db
from .models import (
    AuditLog,
    BeltSpec,
    BearingSpec,
    Brand,
    Category,
    LubricantSpec,
    Order,
    OrderItem,
    Product,
    ProductImage,
    ProductSlugRedirect,
    SealSpec,
    StoreSettings,
    User,
)
from .security import (
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
    verify_password,
    get_session_secret,
)
from .services.catalog import build_catalog_statement, normalize_belt_profile, normalize_category_code
from .services.email_service import send_password_reset_email
from .services.liqpay import (
    LiqPayError,
    configured as liqpay_configured,
    create_checkout as create_liqpay_checkout,
    map_payment_status as map_liqpay_payment_status,
    payment_status as liqpay_payment_status,
    refund_payment as liqpay_refund_payment,
    verify_and_decode_callback as verify_liqpay_callback,
)
from .services.monobank import configured as monobank_configured
from .services.monobank import create_invoice, invoice_status, parse_webhook, verify_webhook
from .services.payment_policy import payment_options
from .services.payment_providers import default_online_provider, online_payment_available
from .services.slug_service import make_unique_product_slug, remember_slug_redirect
from .services.stock_service import (
    InsufficientStock,
    mark_new_order_stock,
    re_reserve_order_stock,
    release_order_stock,
    sync_stock_after_payment,
    reserve_product,
)
from .services.image_service import save_product_image
from .services.nova_poshta import configured as nova_poshta_configured, search_cities, search_warehouses
from .seo import catalog_seo_context, default_seo_context, merchant_feed_xml, product_seo_context, robots_txt, sitemap_xml
from .rate_limit import SimpleRateLimitMiddleware

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
TEMPLATE_DIR = BASE_DIR / "templates"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PRODUCT_IMAGES = 8
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

PRODUCT_TYPE_LABELS = {
    "bearings": "Підшипники",
    "belts": "Пасові ремені",
    "seals": "Сальники та манжети",
    "lubricants": "Змащення",
    "accessories": "Аксесуари / комплектуючі",
    "generic": "Загальний товар",
}

ORDER_STATUS_LABELS = {
    "new": "Нове",
    "processing": "Оброблено",
    "shipped": "Відправлено",
    "cancelled": "Скасовано",
}
PAYMENT_STATUS_LABELS = {
    "unpaid": "Не оплачено",
    "awaiting_payment": "Очікує оплату",
    "pending": "Оплата в процесі",
    "paid": "Оплачено",
    "failed": "Помилка оплати",
    "refund_pending": "Повернення в процесі",
    "refunded": "Повернено",
}
PAYMENT_METHOD_LABELS = {
    "online": "Онлайн-оплата",
    "bank_transfer": "Оплата за рахунком / безготівково",
    "cod": "Післяплата при отриманні",
}
DELIVERY_LABELS = {
    "nova_poshta": "Нова пошта",
    "ukrposhta": "Укрпошта",
    "pickup": "Самовивіз",
}


def _bootstrap_data() -> None:
    with SessionLocal() as db:
        no_brand = db.scalar(select(Brand).where(Brand.name == "Без бренду"))
        if not no_brand:
            db.add(Brand(name="Без бренду", slug="bez-brendu"))

        settings = db.get(StoreSettings, 1)
        if not settings:
            db.add(
                StoreSettings(
                    id=1,
                    cod_enabled=True,
                    cod_min_total=Decimal("500.00"),
                    online_payment_enabled=True,
                    bank_transfer_enabled=True,
                    shipping_notice="Відправка замовлень відбувається протягом 1–3 робочих днів.",
                )
            )
        db.commit()

_bootstrap_data()

app = FastAPI(title="TopBearing")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
COOKIE_SECURE = APP_ENV == "production" or os.getenv("COOKIE_SECURE", "0") == "1"
app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    session_cookie="topbearing_session",
    same_site="lax",
    https_only=COOKIE_SECURE,
    max_age=60 * 60 * 24 * 14,
)
app.add_middleware(SimpleRateLimitMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://www.google-analytics.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.monobank.ua https://www.liqpay.ua https://api.novaposhta.ua https://www.google-analytics.com; "
        "form-action 'self' https://www.liqpay.ua https://*.liqpay.ua; "
        "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    )
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith(("/admin", "/account", "/checkout", "/order/")):
        response.headers["Cache-Control"] = "no-store"
    return response


def money(value: Any) -> str:
    try:
        number = Decimal(value or 0)
    except Exception:
        number = Decimal("0")
    return f"{number:,.0f}".replace(",", " ")


def category_kind(code: str | None) -> str:
    return normalize_category_code(code) or (code or "")


def category_product_type(category: Category | None) -> str:
    if not category:
        return "generic"
    return normalize_category_code(category.product_type) or "generic"


def product_size_label(product: Product) -> str | None:
    """Short, customer-facing size label used on catalogue cards."""
    kind = category_product_type(product.category)
    if kind == "bearings" and product.bearing_spec:
        spec = product.bearing_spec
        if all(value is not None for value in (spec.inner_diameter_mm, spec.outer_diameter_mm, spec.width_mm)):
            return f"{clean_number(spec.inner_diameter_mm)} × {clean_number(spec.outer_diameter_mm)} × {clean_number(spec.width_mm)} мм"
    if kind == "seals" and product.seal_spec:
        spec = product.seal_spec
        if all(value is not None for value in (spec.inner_diameter_mm, spec.outer_diameter_mm, spec.width_mm)):
            return f"{clean_number(spec.inner_diameter_mm)} × {clean_number(spec.outer_diameter_mm)} × {clean_number(spec.width_mm)} мм"
    if kind == "belts" and product.belt_spec:
        spec = product.belt_spec
        if spec.profile and spec.length_mm is not None:
            return f"{spec.profile} / {clean_number(spec.length_mm)} мм"
        if spec.length_mm is not None:
            return f"{clean_number(spec.length_mm)} мм"
        if spec.profile:
            return spec.profile
    if kind == "lubricants" and product.lubricant_spec and product.lubricant_spec.package_size:
        return product.lubricant_spec.package_size
    return None


def product_display_brand(product: Product) -> str | None:
    if product.brand and product.brand.name != "Без бренду":
        return product.brand.name
    return None


def product_origin_label(product: Product) -> str | None:
    if product_display_brand(product):
        return None
    return (product.manufacturing_country or "").strip() or None


def product_media_url(product: Product) -> str:
    if product.primary_image:
        return product.primary_image
    if category_product_type(product.category) in {"bearings", "belts", "seals"}:
        return f"/product/{product.id}/diagram.svg"
    return "/static/img/product-placeholder.svg"


def availability_label(product: Product) -> str:
    return {
        "in_stock": "В наявності",
        "out_of_stock": "Немає в наявності",
        "on_order": "Під замовлення",
    }.get(product.storefront_availability, "В наявності")


def alternative_marking_list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").splitlines() if item.strip()]


def clean_number(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def client_order_status_label(order: Order) -> str:
    # "new" is useful internally for the admin queue, but to a customer the
    # order has already been accepted and is being processed.
    if order.status == "new":
        return "В обробці"
    return ORDER_STATUS_LABELS.get(order.status, order.status)


def client_payment_status_label(order: Order) -> str:
    if order.payment_method == "bank_transfer" and order.payment_status == "awaiting_payment":
        return "Очікує підтвердження менеджера"
    if order.payment_method == "cod" and order.payment_status == "unpaid":
        return "Оплата при отриманні"
    return PAYMENT_STATUS_LABELS.get(order.payment_status, order.payment_status)


def telegram_href(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("https://") or raw.startswith("http://"):
        return raw
    handle = raw.lstrip("@").strip()
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", handle):
        return f"https://t.me/{handle}"
    return None


def viber_href(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("viber://") or raw.startswith("https://") or raw.startswith("http://"):
        return raw
    digits = re.sub(r"[^0-9+]", "", raw)
    if digits.startswith("+") and len(re.sub(r"\D", "", digits)) >= 9:
        return f"viber://chat?number={quote(digits, safe='')}"
    return None


templates.env.filters["money"] = money
templates.env.filters["clean_number"] = clean_number
templates.env.filters["category_kind"] = category_kind
templates.env.globals.update(
    availability_label=availability_label,
    category_product_type=category_product_type,
    product_size_label=product_size_label,
    product_display_brand=product_display_brand,
    product_origin_label=product_origin_label,
    product_media_url=product_media_url,
    product_type_labels=PRODUCT_TYPE_LABELS,
    order_status_labels=ORDER_STATUS_LABELS,
    payment_status_labels=PAYMENT_STATUS_LABELS,
    payment_method_labels=PAYMENT_METHOD_LABELS,
    delivery_labels=DELIVERY_LABELS,
    alternative_marking_list=alternative_marking_list,
    client_order_status_label=client_order_status_label,
    client_payment_status_label=client_payment_status_label,
    telegram_href=telegram_href,
    viber_href=viber_href,
)


def _settings(db: Session) -> StoreSettings:
    settings = db.get(StoreSettings, 1)
    if not settings:
        settings = StoreSettings(id=1, cod_min_total=Decimal("500.00"))
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        request.session.pop("user_id", None)
        return None
    return user


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, form: Any) -> None:
    expected = request.session.get("csrf_token")
    supplied = str(form.get("csrf_token", ""))
    if not expected or not supplied or not secrets.compare_digest(str(expected), supplied):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def flash(request: Request, message: str, kind: str = "info") -> None:
    items = request.session.setdefault("flashes", [])
    items.append({"message": message, "kind": kind})
    request.session["flashes"] = items[-5:]


def pop_flashes(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flashes", [])


def _cart_map(request: Request) -> dict[str, int]:
    raw = request.session.get("cart", {})
    result: dict[str, int] = {}
    for key, value in raw.items():
        try:
            qty = max(1, min(999, int(value)))
            result[str(int(key))] = qty
        except Exception:
            continue
    return result


def cart_count(request: Request) -> int:
    return sum(_cart_map(request).values())


def cart_details(request: Request, db: Session):
    cart = _cart_map(request)
    if not cart:
        return [], Decimal("0.00")
    ids = [int(k) for k in cart]
    products = db.scalars(
        select(Product)
        .where(Product.id.in_(ids), Product.is_active.is_(True))
        .options(selectinload(Product.images), selectinload(Product.brand), selectinload(Product.category))
    ).all()
    items = []
    subtotal = Decimal("0.00")
    for product in products:
        qty = cart.get(str(product.id), 1)
        if product.stock_is_tracked:
            qty = min(qty, max(product.stock_qty, 0)) if product.stock_qty > 0 else 0
        if qty <= 0 or product.storefront_availability == "out_of_stock":
            continue
        line_total = Decimal(product.price) * qty
        subtotal += line_total
        items.append({"product": product, "qty": qty, "line_total": line_total})
    return items, subtotal


def base_context(request: Request, db: Session, **extra: Any) -> dict[str, Any]:
    category_stmt = select(Category)
    if not request.url.path.startswith("/admin"):
        category_stmt = category_stmt.where(Category.is_active.is_(True), Category.show_in_menu.is_(True))
    categories = db.scalars(category_stmt.order_by(Category.sort_order, Category.name, Category.id)).all()
    by_parent: dict[int | None, list[Category]] = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)
    root_categories = by_parent.get(None, [])
    ctx = {
        "request": request,
        "current_user": current_user(request, db),
        "cart_count": cart_count(request),
        "csrf_token": csrf_token(request),
        "categories": categories,
        "root_categories": root_categories,
        "category_children": by_parent,
        "settings": _settings(db),
        "flashes": pop_flashes(request),
        "mono_ready": monobank_configured(),
        "liqpay_ready": liqpay_configured(),
        "online_payment_ready": online_payment_available(),
        "online_provider": default_online_provider(),
        "nova_poshta_ready": nova_poshta_configured(),
    }
    ctx.update(default_seo_context(request))
    ctx.update(extra)
    return ctx


def render(request: Request, db: Session, name: str, status_code: int = 200, **extra: Any):
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=base_context(request, db, **extra),
        status_code=status_code,
    )


def find_category_by_code(db: Session, code: str | None, *, active_only: bool = False) -> Category | None:
    if not code:
        return None
    raw = code.strip().lower()
    stmt = select(Category).where(func.lower(Category.code) == raw)
    if active_only:
        stmt = stmt.where(Category.is_active.is_(True))
    category = db.scalar(stmt)
    if category:
        return category
    # Backwards-compatible aliases for old links such as /catalog/bearing.
    canonical = normalize_category_code(raw)
    if canonical and canonical != raw:
        stmt = select(Category).where(Category.code == canonical)
        if active_only:
            stmt = stmt.where(Category.is_active.is_(True))
        return db.scalar(stmt)
    return None


def category_descendant_ids(db: Session, category: Category, *, active_only: bool = True) -> list[int]:
    stmt = select(Category.id, Category.parent_id)
    if active_only:
        stmt = stmt.where(Category.is_active.is_(True))
    rows = db.execute(stmt).all()
    children: dict[int | None, list[int]] = {}
    for category_id, parent_id in rows:
        children.setdefault(parent_id, []).append(category_id)
    result: list[int] = []
    pending = [category.id]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        pending.extend(children.get(current, []))
    return result


def pagination_items(page: int, pages: int, radius: int = 2) -> list[int | None]:
    if pages <= 9:
        return list(range(1, pages + 1))
    wanted = {1, pages}
    for item in range(max(1, page - radius), min(pages, page + radius) + 1):
        wanted.add(item)
    ordered = sorted(wanted)
    result: list[int | None] = []
    previous = None
    for item in ordered:
        if previous is not None and item - previous > 1:
            result.append(None)
        result.append(item)
        previous = item
    return result


def safe_next(value: str | None, fallback: str = "/") -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return fallback


def as_decimal(value: str | None, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        return Decimal(value.replace(",", "."))
    except (InvalidOperation, AttributeError):
        return default


def as_int(value: str | None, default: int | None = None) -> int | None:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


_TRANSLIT = str.maketrans({
    "а":"a","б":"b","в":"v","г":"h","ґ":"g","д":"d","е":"e","є":"ye","ж":"zh","з":"z","и":"y","і":"i","ї":"yi","й":"y",
    "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch",
    "ш":"sh","щ":"shch","ь":"","ю":"yu","я":"ya","ы":"y","э":"e","ё":"yo","ъ":"",
})

def slugify(value: str, lowercase: bool = True, max_length: int = 180) -> str:
    text = (value or "").strip().lower().translate(_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)[:max_length].rstrip("-")
    return text if lowercase else text.upper()


def make_unique_slug(db: Session, name: str, product_id: int | None = None) -> str:
    base = slugify(name, lowercase=True, max_length=180) or "product"
    candidate = base
    counter = 2
    while True:
        existing = db.scalar(select(Product).where(Product.slug == candidate))
        if not existing or existing.id == product_id:
            return candidate
        candidate = f"{base}-{counter}"
        counter += 1


def generate_sku(db: Session, category_code: str) -> str:
    prefix = {
        "bearings": "BRG",
        "belts": "BLT",
        "seals": "SEA",
        "lubricants": "LUB",
        "accessories": "ACC",
    }.get(category_kind(category_code), "PRD")
    while True:
        sku = f"TB-{prefix}-{secrets.token_hex(3).upper()}"
        if not db.scalar(select(Product).where(Product.sku == sku)):
            return sku


def make_unique_category_code(
    db: Session,
    name: str,
    *,
    category_id: int | None = None,
    requested_code: str | None = None,
) -> str:
    base = slugify(requested_code or name, lowercase=True, max_length=60) or "category"
    candidate = base
    index = 2
    while True:
        existing = db.scalar(select(Category).where(Category.code == candidate))
        if not existing or existing.id == category_id:
            return candidate
        suffix = f"-{index}"
        candidate = f"{base[:60-len(suffix)]}{suffix}"
        index += 1


def normalize_alternative_markings(value: str | None, primary: str | None = None) -> str | None:
    primary_key = (primary or "").strip().casefold()
    result: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\r\n,;]+", value or ""):
        item = re.sub(r"\s+", " ", raw).strip()
        if not item:
            continue
        item = item[:120]
        key = item.casefold()
        if key == primary_key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 30:
            break
    return "\n".join(result) or None


def get_or_create_brand(
    db: Session,
    brand_name: str | None,
    brand_country: str | None = None,
) -> Brand | None:
    cleaned = (brand_name or "").strip()
    if not cleaned or cleaned.casefold() == "без бренду":
        return None
    country = (brand_country or "").strip()[:120] or None
    brand = next(
        (item for item in db.scalars(select(Brand)).all() if item.name.casefold() == cleaned.casefold()),
        None,
    )
    if brand:
        # Empty input does not erase a previously known country.
        if country:
            brand.country = country
        return brand

    base = slugify(cleaned, lowercase=True) or "brand"
    candidate = base
    index = 2
    while db.scalar(select(Brand).where(Brand.slug == candidate)):
        candidate = f"{base}-{index}"
        index += 1

    brand = Brand(name=cleaned, slug=candidate, country=country)
    db.add(brand)
    db.flush()
    return brand

def audit(db: Session, user: User | None, action: str, entity_type: str | None = None, entity_id: Any = None, details: str | None = None):
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action[:120],
            entity_type=entity_type or None,
            entity_id=str(entity_id)[:80] if entity_id is not None else None,
            details=details or None,
        )
    )


def order_number() -> str:
    return f"TB-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"


def _parse_payment_event_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def apply_payment_event(order: Order, data: dict) -> None:
    incoming_time = _parse_payment_event_time(data.get("modifiedDate"))
    if order.payment_event_at and incoming_time and incoming_time < order.payment_event_at:
        return
    if incoming_time:
        order.payment_event_at = incoming_time
    status = data.get("status")
    if status == "success":
        order.payment_status = "paid"
        if not order.paid_at:
            order.paid_at = datetime.utcnow()
    elif status in {"created", "processing", "hold"}:
        if order.payment_status != "paid":
            order.payment_status = "pending"
    elif status in {"failure", "expired"}:
        if order.payment_status != "paid":
            order.payment_status = "failed"
    elif status == "reversed":
        order.payment_status = "refunded"
        order.refunded_at = datetime.utcnow()


def _public_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _can_access_order(request: Request, db: Session, order: Order) -> bool:
    if request.session.get("last_order_id") == order.id:
        return True
    user = current_user(request, db)
    return bool(user and (user.role == "admin" or order.user_id == user.id))


def _liqpay_checkout_html(action_url: str, data: str, signature: str) -> str:
    action = html.escape(action_url, quote=True)
    encoded_data = html.escape(data, quote=True)
    encoded_signature = html.escape(signature, quote=True)
    return f"""<!doctype html>
<html lang=\"uk\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <meta name=\"robots\" content=\"noindex,nofollow\">
  <title>Перехід до оплати — TopBearing</title>
</head>
<body>
  <p>Переходимо до захищеної сторінки оплати LiqPay…</p>
  <form id=\"liqpay-checkout\" method=\"post\" action=\"{action}\" accept-charset=\"utf-8\">
    <input type=\"hidden\" name=\"data\" value=\"{encoded_data}\">
    <input type=\"hidden\" name=\"signature\" value=\"{encoded_signature}\">
    <noscript><button type=\"submit\">Продовжити оплату</button></noscript>
  </form>
  <script>document.getElementById('liqpay-checkout').submit();</script>
</body>
</html>"""


def _validate_liqpay_order_payload(order: Order, data: dict, *, require_amount: bool = True) -> None:
    if str(data.get("order_id", "")).strip() != order.number:
        raise ValueError("LiqPay order_id mismatch")
    if require_amount:
        if str(data.get("currency", "")).upper() != "UAH":
            raise ValueError("LiqPay currency mismatch")
        try:
            incoming = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
            expected = Decimal(str(order.total)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Invalid LiqPay amount") from exc
        if incoming != expected:
            raise ValueError("LiqPay amount mismatch")


def apply_liqpay_payment_event(order: Order, data: dict) -> None:
    mapped = map_liqpay_payment_status(str(data.get("status", "")))
    if mapped is None:
        return

    order.payment_provider = "liqpay"

    # A delayed callback must not undo a refund request or a confirmed payment.
    if order.payment_status == "refund_pending" and mapped != "refunded":
        return
    if order.payment_status == "paid" and mapped not in {"paid", "refunded"}:
        return

    order.payment_status = mapped
    if mapped == "paid":
        if not order.paid_at:
            order.paid_at = datetime.utcnow()
    elif mapped == "refunded":
        order.refunded_at = datetime.utcnow()

def _start_monobank_payment(order: Order, request: Request, db: Session):
    if not monobank_configured():
        raise RuntimeError("Monobank acquiring is not configured")
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    redirect_url = f"{base}/payment/return?provider=monobank" if base else f"{request.url_for('payment_return')}?provider=monobank"
    webhook_url = f"{base}/payments/monobank/webhook" if base else None
    invoice = create_invoice(order=order, redirect_url=redirect_url, webhook_url=webhook_url)
    order.mono_invoice_id = invoice["invoiceId"]
    order.payment_provider = "monobank"
    order.payment_status = "pending"
    db.commit()
    return RedirectResponse(invoice["pageUrl"], status_code=303)


def _start_online_payment(order: Order, request: Request, db: Session):
    provider = default_online_provider()
    if provider == "liqpay":
        order.payment_provider = "liqpay"
        db.commit()
        return RedirectResponse(f"/payments/liqpay/{order.number}", status_code=303)
    if provider == "monobank":
        return _start_monobank_payment(order, request, db)
    raise RuntimeError("No online payment provider is configured")


@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True})


@app.get("/robots.txt", include_in_schema=False)
def robots(request: Request):
    return HTMLResponse(robots_txt(request), media_type="text/plain; charset=utf-8")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request, db: Session = Depends(get_db)):
    return HTMLResponse(sitemap_xml(request, db), media_type="application/xml; charset=utf-8")


@app.get("/merchant-feed.xml", include_in_schema=False)
def merchant_feed(request: Request, db: Session = Depends(get_db)):
    return HTMLResponse(merchant_feed_xml(request, db), media_type="application/xml; charset=utf-8")


@app.get("/api/nova-poshta/cities")
async def nova_poshta_cities(q: str = ""):
    return JSONResponse(await search_cities(q) if nova_poshta_configured() else [])


@app.get("/api/nova-poshta/warehouses")
async def nova_poshta_warehouses(city_ref: str = "", q: str = ""):
    return JSONResponse(await search_warehouses(city_ref, q) if nova_poshta_configured() else [])


@app.get("/api/catalog/brands")
def catalog_brand_options(category: str = "", db: Session = Depends(get_db)):
    """Return only brands that have active products in the selected category.

    The endpoint updates the dependent brand select without submitting the
    whole filter form, so customers can still apply filters explicitly.
    """
    category_obj = find_category_by_code(db, category, active_only=True) if category else None
    if category and not category_obj:
        return JSONResponse([])
    category_ids = category_descendant_ids(db, category_obj) if category_obj else None
    stmt = (
        select(Brand)
        .join(Product, Product.brand_id == Brand.id)
        .where(Product.is_active.is_(True), Brand.name != "Без бренду")
        .distinct()
        .order_by(Brand.name)
    )
    if category_ids:
        stmt = stmt.where(Product.category_id.in_(category_ids))
    brands = db.scalars(stmt).all()
    return JSONResponse([{"id": brand.id, "name": brand.name} for brand in brands])


# --------------------------- Storefront ---------------------------


def _product_card_options():
    return (
        selectinload(Product.images),
        selectinload(Product.brand),
        selectinload(Product.category),
        selectinload(Product.bearing_spec),
        selectinload(Product.belt_spec),
        selectinload(Product.seal_spec),
        selectinload(Product.lubricant_spec),
    )


def _popular_products(db: Session, limit: int = 8) -> list[Product]:
    sales = (
        select(OrderItem.product_id.label("product_id"), func.sum(OrderItem.qty).label("sold_qty"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.product_id.is_not(None), Order.status != "cancelled")
        .group_by(OrderItem.product_id)
        .subquery()
    )
    return db.scalars(
        select(Product)
        .join(sales, sales.c.product_id == Product.id)
        .where(Product.is_active.is_(True))
        .order_by(sales.c.sold_qty.desc(), Product.id.desc())
        .limit(limit)
        .options(*_product_card_options())
    ).all()


def _similar_products(db: Session, product: Product, limit: int = 4) -> list[Product]:
    kind = category_product_type(product.category)
    stmt = select(Product).where(
        Product.is_active.is_(True),
        Product.id != product.id,
        Product.category.has(Category.product_type == kind),
    )

    exact_filter = None
    if kind == "bearings" and product.bearing_spec:
        spec = product.bearing_spec
        if all(value is not None for value in (spec.inner_diameter_mm, spec.outer_diameter_mm, spec.width_mm)):
            target = Product.bearing_spec.property.mapper.class_
            exact_filter = Product.bearing_spec.has(
                and_(
                    target.inner_diameter_mm == spec.inner_diameter_mm,
                    target.outer_diameter_mm == spec.outer_diameter_mm,
                    target.width_mm == spec.width_mm,
                )
            )
    elif kind == "seals" and product.seal_spec:
        spec = product.seal_spec
        if all(value is not None for value in (spec.inner_diameter_mm, spec.outer_diameter_mm, spec.width_mm)):
            target = Product.seal_spec.property.mapper.class_
            exact_filter = Product.seal_spec.has(
                and_(
                    target.inner_diameter_mm == spec.inner_diameter_mm,
                    target.outer_diameter_mm == spec.outer_diameter_mm,
                    target.width_mm == spec.width_mm,
                )
            )
    elif kind == "belts" and product.belt_spec:
        spec = product.belt_spec
        target = Product.belt_spec.property.mapper.class_
        parts = []
        if spec.profile:
            parts.append(func.upper(func.coalesce(target.profile, "")) == normalize_belt_profile(spec.profile))
        if spec.length_mm is not None:
            parts.append(target.length_mm == spec.length_mm)
        if parts:
            exact_filter = Product.belt_spec.has(and_(*parts))

    if exact_filter is not None:
        exact = db.scalars(
            stmt.where(exact_filter)
            .order_by(Product.is_featured.desc(), Product.id.desc())
            .limit(limit)
            .options(*_product_card_options())
        ).all()
        if len(exact) >= limit:
            return exact
    else:
        exact = []

    excluded = {product.id, *(item.id for item in exact)}
    # Fallback stays within the selected subcategory. If it is sparse, use the
    # same product type so the section is still relevant rather than random.
    fallback = db.scalars(
        select(Product)
        .where(
            Product.is_active.is_(True),
            Product.id.not_in(excluded),
            or_(
                Product.category_id == product.category_id,
                Product.category.has(Category.product_type == kind),
            ),
        )
        .order_by((Product.category_id == product.category_id).desc(), Product.is_featured.desc(), Product.id.desc())
        .limit(max(0, limit - len(exact)))
        .options(*_product_card_options())
    ).all()
    return [*exact, *fallback]


def _bought_together_products(db: Session, product: Product, limit: int = 4) -> list[Product]:
    selected_item = aliased(OrderItem)
    other_item = aliased(OrderItem)
    rows = db.execute(
        select(other_item.product_id, func.sum(other_item.qty).label("weight"))
        .join(selected_item, selected_item.order_id == other_item.order_id)
        .join(Order, Order.id == other_item.order_id)
        .where(
            selected_item.product_id == product.id,
            other_item.product_id.is_not(None),
            other_item.product_id != product.id,
            Order.status != "cancelled",
        )
        .group_by(other_item.product_id)
        .order_by(func.sum(other_item.qty).desc())
        .limit(limit)
    ).all()
    ids = [int(row.product_id) for row in rows if row.product_id is not None]
    if not ids:
        return []
    products = db.scalars(
        select(Product).where(Product.id.in_(ids), Product.is_active.is_(True)).options(*_product_card_options())
    ).all()
    by_id = {item.id: item for item in products}
    return [by_id[item] for item in ids if item in by_id]


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    featured = db.scalars(
        select(Product)
        .where(Product.is_active.is_(True), Product.is_featured.is_(True))
        .order_by(Product.updated_at.desc(), Product.id.desc())
        .limit(8)
        .options(*_product_card_options())
    ).all()
    featured_title = "Рекомендовані товари"
    if not featured:
        featured = _popular_products(db, 8)
        featured_title = "Популярні товари"
    if not featured:
        featured = db.scalars(
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.updated_at.desc(), Product.id.desc())
            .limit(8)
            .options(*_product_card_options())
        ).all()
        featured_title = "Актуальні товари"
    return render(request, db, "home.html", featured=featured, featured_title=featured_title)


def _catalog_response(request: Request, db: Session, *, category_code_override: str | None = None):
    params = request.query_params
    category_code = category_code_override or params.get("category")
    category_obj = find_category_by_code(db, category_code, active_only=True) if category_code else None
    category_ids = category_descendant_ids(db, category_obj) if category_obj else None
    product_type = category_product_type(category_obj) if category_obj else None
    brand_id = as_int(params.get("brand"))
    sort = params.get("sort", "relevance")
    page = max(1, as_int(params.get("page"), 1) or 1)
    page_size = as_int(params.get("per_page"), 24) or 24
    if page_size not in {24, 50, 100, 200}:
        page_size = 24
    catalog_filters = dict(
        q=params.get("q"),
        category_code=category_code,
        category_ids=category_ids,
        product_type=product_type,
        sort=sort,
        subtype=params.get("subtype"),
        profile=params.get("profile"),
        material=params.get("material"),
        viscosity=params.get("viscosity"),
        rows=params.get("rows"),
        series_type=params.get("series_type"),
        inner_min=params.get("inner_min"),
        inner_max=params.get("inner_max"),
        outer_min=params.get("outer_min"),
        outer_max=params.get("outer_max"),
        width_min=params.get("width_min"),
        width_max=params.get("width_max"),
        length_min=params.get("length_min"),
        length_max=params.get("length_max"),
    )
    stmt = build_catalog_statement(brand_id=brand_id, **catalog_filters)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    pages = max(1, (total + page_size - 1) // page_size)
    if page > pages:
        page = pages
    products = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    # Brand options must come only from products that match the current
    # catalogue scope (category + technical/search filters), ignoring only the
    # brand filter itself. This prevents irrelevant brands from appearing in
    # bearing/belt/etc. categories.
    brand_scope = build_catalog_statement(brand_id=None, **catalog_filters).order_by(None).subquery()
    brand_stmt = (
        select(Brand)
        .join(brand_scope, brand_scope.c.brand_id == Brand.id)
        .where(Brand.name != "Без бренду")
        .distinct()
        .order_by(Brand.name)
    )
    brands = db.scalars(brand_stmt).all()

    filter_keys = {
        "q", "brand", "sort", "subtype", "profile", "material", "viscosity", "rows", "series_type",
        "inner_min", "inner_max", "outer_min", "outer_max", "width_min", "width_max",
        "length_min", "length_max", "page", "per_page",
    }
    seo = catalog_seo_context(request, category_obj, has_filters=any(params.get(key) for key in filter_keys))
    return render(
        request,
        db,
        "catalog.html",
        products=products,
        total=total,
        brands=brands,
        active_category=category_obj.code if category_obj else None,
        active_category_obj=category_obj,
        active_product_type=product_type,
        params=dict(params),
        page=page,
        pages=pages,
        per_page=page_size,
        pagination_items=pagination_items(page, pages),
        **seo,
    )


@app.get("/catalog", response_class=HTMLResponse)
def catalog(request: Request, db: Session = Depends(get_db)):
    category = request.query_params.get("category")
    if category and len(request.query_params) == 1:
        return RedirectResponse(f"/catalog/{category_kind(category)}", status_code=301)
    return _catalog_response(request, db)


@app.get("/catalog/{category_code}", response_class=HTMLResponse)
def catalog_category(category_code: str, request: Request, db: Session = Depends(get_db)):
    category = find_category_by_code(db, category_code, active_only=True)
    if not category:
        raise HTTPException(status_code=404)
    return _catalog_response(request, db, category_code_override=category.code)


@app.get("/product/{slug}", response_class=HTMLResponse)
def product_page(slug: str, request: Request, db: Session = Depends(get_db)):
    product = db.scalar(
        select(Product)
        .where(Product.slug == slug, Product.is_active.is_(True))
        .options(
            selectinload(Product.images),
            selectinload(Product.brand),
            selectinload(Product.category),
            selectinload(Product.bearing_spec),
            selectinload(Product.belt_spec),
            selectinload(Product.seal_spec),
            selectinload(Product.lubricant_spec),
        )
    )
    if not product:
        redirect = db.scalar(
            select(ProductSlugRedirect)
            .where(ProductSlugRedirect.old_slug == slug)
            .options(selectinload(ProductSlugRedirect.product))
        )
        if redirect and redirect.product and redirect.product.is_active:
            return RedirectResponse(f"/product/{redirect.product.slug}", status_code=301)
        raise HTTPException(status_code=404)
    related = _similar_products(db, product, 4)
    bought_together = _bought_together_products(db, product, 4)
    return render(
        request,
        db,
        "product.html",
        product=product,
        related=related,
        bought_together=bought_together,
        **product_seo_context(request, product),
    )


@app.get("/product/{product_id}/diagram.svg", include_in_schema=False)
def product_diagram(product_id: int, db: Session = Depends(get_db)):
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id, Product.is_active.is_(True))
        .options(
            selectinload(Product.category),
            selectinload(Product.bearing_spec),
            selectinload(Product.belt_spec),
            selectinload(Product.seal_spec),
        )
    )
    if not product:
        raise HTTPException(status_code=404)
    kind = category_product_type(product.category)
    size = product_size_label(product) or "Розмір не вказано"
    safe_name = html.escape(product.name[:54])
    safe_size = html.escape(size)
    if kind in {"bearings", "seals"}:
        shape = """
        <circle cx="205" cy="137" r="84" fill="none" stroke="#7b92aa" stroke-width="18"/>
        <circle cx="205" cy="137" r="39" fill="#f8fbff" stroke="#7b92aa" stroke-width="5"/>
        <line x1="121" y1="42" x2="289" y2="42" stroke="#0d6efd" stroke-width="2"/>
        <line x1="121" y1="34" x2="121" y2="50" stroke="#0d6efd" stroke-width="2"/>
        <line x1="289" y1="34" x2="289" y2="50" stroke="#0d6efd" stroke-width="2"/>
        <text x="205" y="29" text-anchor="middle" class="dim">D</text>
        <line x1="166" y1="137" x2="244" y2="137" stroke="#0d6efd" stroke-width="2"/>
        <text x="205" y="126" text-anchor="middle" class="dim">d</text>
        """
    elif kind == "belts":
        shape = """
        <path d="M118 70 H292 L264 206 H146 Z" fill="#eef4fb" stroke="#7b92aa" stroke-width="5"/>
        <line x1="118" y1="45" x2="292" y2="45" stroke="#0d6efd" stroke-width="2"/>
        <line x1="118" y1="37" x2="118" y2="53" stroke="#0d6efd" stroke-width="2"/>
        <line x1="292" y1="37" x2="292" y2="53" stroke="#0d6efd" stroke-width="2"/>
        <text x="205" y="31" text-anchor="middle" class="dim">Профіль</text>
        """
    else:
        shape = '<rect x="110" y="55" width="190" height="150" rx="22" fill="#eef4fb" stroke="#7b92aa" stroke-width="5"/>'
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 410 320" role="img" aria-label="Схематичне зображення {safe_name}">
    <style>text{{font-family:Arial,sans-serif;fill:#16324f}}.dim{{font-size:18px;font-weight:700;fill:#0d6efd}}.title{{font-size:17px;font-weight:700}}.size{{font-size:18px;font-weight:700}}</style>
    <rect width="410" height="320" fill="#f7faff"/>{shape}
    <text x="205" y="253" text-anchor="middle" class="title">{safe_name}</text>
    <text x="205" y="280" text-anchor="middle" class="size">{safe_size}</text>
    <text x="205" y="304" text-anchor="middle" font-size="12" fill="#718399">Схематичне зображення, не в масштабі</text>
    </svg>"""
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


@app.post("/cart/add/{product_id}")
async def cart_add(product_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    product = db.get(Product, product_id)
    if not product or not product.is_active or product.storefront_availability == "out_of_stock":
        flash(request, "Товар зараз недоступний.", "error")
        return RedirectResponse(safe_next(form.get("next"), "/catalog"), status_code=303)
    qty = max(1, min(999, as_int(form.get("qty"), 1) or 1))
    cart = _cart_map(request)
    new_qty = cart.get(str(product_id), 0) + qty
    if product.stock_is_tracked:
        new_qty = min(new_qty, product.stock_qty)
    cart[str(product_id)] = max(1, new_qty)
    request.session["cart"] = cart
    flash(request, "Товар додано до кошика.", "success")
    return RedirectResponse(safe_next(form.get("next"), "/cart"), status_code=303)


@app.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request, db: Session = Depends(get_db)):
    items, subtotal = cart_details(request, db)
    return render(request, db, "cart.html", items=items, subtotal=subtotal)


@app.post("/cart/update")
async def cart_update(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    cart = _cart_map(request)
    for key in list(cart.keys()):
        qty = as_int(form.get(f"qty_{key}"), cart[key]) or 0
        if qty <= 0:
            cart.pop(key, None)
            continue
        product = db.get(Product, int(key))
        if product and product.stock_is_tracked:
            qty = min(qty, product.stock_qty)
        cart[key] = max(1, min(qty, 999))
    request.session["cart"] = cart
    return RedirectResponse("/cart", status_code=303)


@app.post("/cart/item/{product_id}")
async def cart_item_update(product_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    product = db.scalar(select(Product).where(Product.id == product_id, Product.is_active.is_(True)))
    if not product:
        raise HTTPException(status_code=404)

    requested_qty = max(1, min(as_int(str(form.get("qty", "1")), 1) or 1, 999))
    if product.stock_is_tracked:
        if product.stock_qty <= 0:
            raise HTTPException(status_code=409, detail="Товару більше немає в наявності.")
        requested_qty = min(requested_qty, product.stock_qty)

    cart = _cart_map(request)
    if str(product_id) not in cart:
        raise HTTPException(status_code=404, detail="Товару немає у кошику.")
    cart[str(product_id)] = requested_qty
    request.session["cart"] = cart

    items, subtotal = cart_details(request, db)
    line = next((item for item in items if item["product"].id == product_id), None)
    return JSONResponse(
        {
            "ok": True,
            "product_id": product_id,
            "qty": requested_qty,
            "line_total": str(line["line_total"] if line else Decimal("0.00")),
            "subtotal": str(subtotal),
            "cart_count": cart_count(request),
        }
    )


@app.post("/cart/remove/{product_id}")
async def cart_remove(product_id: int, request: Request):
    form = await request.form()
    verify_csrf(request, form)
    cart = _cart_map(request)
    cart.pop(str(product_id), None)
    request.session["cart"] = cart
    return RedirectResponse("/cart", status_code=303)


# --------------------------- Auth / account ---------------------------


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/account", status_code=303)
    return render(request, db, "login.html", next_url=request.query_params.get("next", ""))


@app.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return render(request, db, "login.html", status_code=400, error="Невірний email або пароль.", next_url=form.get("next", ""))
    request.session["user_id"] = user.id
    request.session.pop("csrf_token", None)
    if user.role == "admin":
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse(safe_next(str(form.get("next", "")), "/account"), status_code=303)


@app.post("/logout")
async def logout(request: Request):
    form = await request.form()
    verify_csrf(request, form)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    return render(request, db, "register.html")


@app.post("/register")
async def register_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    email = str(form.get("email", "")).strip().lower()
    full_name = str(form.get("full_name", "")).strip()
    phone = str(form.get("phone", "")).strip()
    password = str(form.get("password", ""))
    confirm = str(form.get("confirm_password", ""))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render(request, db, "register.html", status_code=400, error="Вкажіть коректний email.")
    if len(password) < 8:
        return render(request, db, "register.html", status_code=400, error="Пароль має містити щонайменше 8 символів.")
    if password != confirm:
        return render(request, db, "register.html", status_code=400, error="Паролі не збігаються.")
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        return render(request, db, "register.html", status_code=400, error="Такий email уже зареєстрований.")
    user = User(email=email, full_name=full_name or None, phone=phone or None, password_hash=hash_password(password), role="customer")
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session["user_id"] = user.id
    return RedirectResponse("/account", status_code=303)


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    return render(request, db, "forgot_password.html")


@app.post("/forgot-password")
async def forgot_password_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    email = str(form.get("email", "")).strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email, User.role == "customer", User.is_active.is_(True)))
    dev_reset_url = None
    if user:
        token = create_password_reset_token(user.id, user.password_hash)
        base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
        reset_url = f"{base}/reset-password?token={token}"
        try:
            sent = send_password_reset_email(user.email, reset_url)
        except Exception:
            sent = False
        if not sent and os.getenv("APP_ENV", "development") != "production":
            dev_reset_url = reset_url
    return render(
        request,
        db,
        "forgot_password.html",
        success="Якщо такий клієнтський акаунт існує, інструкція для відновлення вже створена.",
        dev_reset_url=dev_reset_url,
    )


@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(token: str, request: Request, db: Session = Depends(get_db)):
    data = decode_password_reset_token(token)
    user = db.get(User, int(data["uid"])) if data else None
    if not user or user.role != "customer" or not decode_password_reset_token(token, user.password_hash):
        return render(request, db, "reset_password.html", status_code=400, invalid=True)
    return render(request, db, "reset_password.html", token=token)


@app.post("/reset-password")
async def reset_password_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    token = str(form.get("token", ""))
    data = decode_password_reset_token(token)
    user = db.get(User, int(data["uid"])) if data else None
    if not user or user.role != "customer" or not decode_password_reset_token(token, user.password_hash):
        return render(request, db, "reset_password.html", status_code=400, invalid=True)
    password = str(form.get("password", ""))
    confirm = str(form.get("confirm_password", ""))
    if len(password) < 8 or password != confirm:
        return render(request, db, "reset_password.html", status_code=400, token=token, error="Перевірте пароль: мінімум 8 символів і обидва поля мають збігатися.")
    user.password_hash = hash_password(password)
    db.commit()
    flash(request, "Пароль змінено. Тепер увійдіть з новим паролем.", "success")
    return RedirectResponse("/login", status_code=303)


@app.get("/account", response_class=HTMLResponse)
def account(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login?next=/account", status_code=303)
    orders = db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).options(selectinload(Order.items))).all()
    return render(request, db, "account.html", user=user, orders=orders)


@app.post("/account/password")
async def account_change_password(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login?next=/account", status_code=303)
    form = await request.form()
    verify_csrf(request, form)
    current = str(form.get("current_password", ""))
    new = str(form.get("new_password", ""))
    confirm = str(form.get("confirm_password", ""))
    if not verify_password(current, user.password_hash):
        flash(request, "Поточний пароль невірний.", "error")
    elif len(new) < 8:
        flash(request, "Новий пароль має містити щонайменше 8 символів.", "error")
    elif new != confirm:
        flash(request, "Нові паролі не збігаються.", "error")
    else:
        user.password_hash = hash_password(new)
        audit(db, user, "password_change", "user", user.id)
        db.commit()
        flash(request, "Пароль успішно змінено.", "success")
    return RedirectResponse("/account", status_code=303)


@app.get("/contacts", response_class=HTMLResponse)
def contacts(request: Request, db: Session = Depends(get_db)):
    return render(request, db, "contacts.html")


# --------------------------- Favorites (works without login) ---------------------------


@app.get("/favorites", response_class=HTMLResponse)
def favorites_page(request: Request, db: Session = Depends(get_db)):
    return render(request, db, "favorites.html")


@app.get("/api/products/batch")
def products_batch(ids: str = "", db: Session = Depends(get_db)):
    clean_ids = []
    for part in ids.split(",")[:100]:
        try:
            clean_ids.append(int(part))
        except ValueError:
            continue
    if not clean_ids:
        return JSONResponse([])
    products = db.scalars(
        select(Product)
        .where(Product.id.in_(clean_ids), Product.is_active.is_(True))
        .options(*_product_card_options())
    ).all()
    product_by_id = {product.id: product for product in products}
    payload = []
    # Keep the same order as localStorage so the favourites page does not jump
    # around after every reload.
    for product_id in clean_ids:
        product = product_by_id.get(product_id)
        if not product:
            continue
        payload.append(
            {
                "id": product.id,
                "name": product.name,
                "brand": product_display_brand(product),
                "origin": product_origin_label(product),
                "price": float(product.price),
                "image": product_media_url(product),
                "url": f"/product/{product.slug}",
                "size_label": product_size_label(product),
                "availability_code": product.storefront_availability,
                "availability": availability_label(product),
            }
        )
    return JSONResponse(payload)


# --------------------------- Checkout / payment ---------------------------


@app.get("/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, db: Session = Depends(get_db)):
    items, subtotal = cart_details(request, db)
    if not items:
        flash(request, "Кошик порожній.", "info")
        return RedirectResponse("/cart", status_code=303)
    settings = _settings(db)
    options = payment_options(subtotal, settings, monobank_ready=online_payment_available(), products=[item["product"] for item in items])
    user = current_user(request, db)
    return render(request, db, "checkout.html", items=items, subtotal=subtotal, payment_options=options, user=user)


@app.post("/checkout")
async def checkout_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    items, subtotal = cart_details(request, db)
    if not items:
        return RedirectResponse("/cart", status_code=303)

    customer_name = str(form.get("customer_name", "")).strip()
    customer_phone = str(form.get("customer_phone", "")).strip()
    customer_email = str(form.get("customer_email", "")).strip().lower()
    delivery_service = str(form.get("delivery_service", "")).strip()
    delivery_city = str(form.get("delivery_city", "")).strip()
    delivery_branch = str(form.get("delivery_branch", "")).strip()
    delivery_postal_code = str(form.get("delivery_postal_code", "")).strip()
    delivery_address = str(form.get("delivery_address", "")).strip()
    payment_method = str(form.get("payment_method", "")).strip()
    comment = str(form.get("comment", "")).strip()

    errors = []
    if len(customer_name) < 2:
        errors.append("Вкажіть ім’я та прізвище отримувача.")
    if len(re.sub(r"\D", "", customer_phone)) < 9:
        errors.append("Вкажіть коректний номер телефону.")
    if customer_email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", customer_email):
        errors.append("Вкажіть коректний email або залиште поле порожнім.")
    if delivery_service not in DELIVERY_LABELS:
        errors.append("Оберіть спосіб доставки.")
    if delivery_service in {"nova_poshta", "ukrposhta"} and not delivery_city:
        errors.append("Вкажіть населений пункт.")
    if delivery_service == "nova_poshta" and not delivery_branch:
        errors.append("Вкажіть відділення або поштомат Нової пошти.")
    if delivery_service == "ukrposhta" and not (delivery_branch or delivery_postal_code):
        errors.append("Вкажіть індекс або відділення Укрпошти.")

    settings = _settings(db)
    options = payment_options(subtotal, settings, monobank_ready=online_payment_available(), products=[item["product"] for item in items])
    allowed_methods = {o["value"] for o in options if o.get("enabled")}
    if payment_method not in allowed_methods:
        errors.append("Оберіть доступний спосіб оплати.")

    for item in items:
        product = item["product"]
        if product.stock_is_tracked and item["qty"] > product.stock_qty:
            errors.append(f"Недостатня кількість товару: {product.name}.")

    if errors:
        return render(
            request,
            db,
            "checkout.html",
            status_code=400,
            items=items,
            subtotal=subtotal,
            payment_options=options,
            user=current_user(request, db),
            errors=errors,
            form_data=dict(form),
        )

    user = current_user(request, db)
    order = Order(
        number=order_number(),
        user_id=user.id if user else None,
        status="new",
        payment_method=payment_method,
        payment_status="pending" if payment_method == "online" else ("awaiting_payment" if payment_method == "bank_transfer" else "unpaid"),
        subtotal=subtotal,
        delivery_price=Decimal("0.00"),
        total=subtotal,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_email=customer_email or (user.email if user else None),
        delivery_service=delivery_service,
        delivery_city=delivery_city or None,
        delivery_branch=delivery_branch or None,
        delivery_postal_code=delivery_postal_code or None,
        delivery_address=delivery_address or None,
        comment=comment or None,
    )
    db.add(order)
    db.flush()

    mark_new_order_stock(order)
    try:
        for item in items:
            qty = item["qty"]
            product = reserve_product(db, item["product"].id, qty)
            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    sku_snapshot=product.sku,
                    name_snapshot=product.name,
                    qty=qty,
                    unit_price=product.price,
                    line_total=Decimal(product.price) * qty,
                )
            )
    except InsufficientStock as exc:
        db.rollback()
        flash(request, str(exc) or "Залишок товару щойно змінився. Перевірте кошик.", "error")
        return RedirectResponse("/cart", status_code=303)

    audit(db, user, "order_create", "order", order.id, order.number)
    db.commit()
    db.refresh(order)
    request.session["cart"] = {}
    request.session["last_order_id"] = order.id

    if payment_method == "online":
        try:
            return _start_online_payment(order, request, db)
        except Exception:
            order.payment_status = "failed"
            order = db.scalar(select(Order).where(Order.id == order.id).options(selectinload(Order.items)))
            sync_stock_after_payment(db, order)
            db.commit()
            flash(request, "Замовлення створено, але платіжну сторінку не вдалося відкрити. Резерв товару звільнено; оплату можна повторити.", "error")

    return RedirectResponse(f"/order/{order.number}/success", status_code=303)


@app.post("/order/{number}/pay")
async def retry_payment(number: str, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    verify_csrf(request, form)
    order = db.scalar(select(Order).where(Order.number == number).options(selectinload(Order.items)))
    if not order:
        raise HTTPException(status_code=404)
    if not _can_access_order(request, db, order):
        raise HTTPException(status_code=403)
    if order.payment_method != "online" or order.payment_status == "paid":
        return RedirectResponse(f"/order/{number}/success", status_code=303)
    if not re_reserve_order_stock(db, order):
        db.rollback()
        flash(request, "Не вдалося повторно зарезервувати товар: залишок уже змінився.", "error")
        return RedirectResponse(f"/order/{number}/success", status_code=303)
    order.payment_status = "pending"
    db.commit()
    try:
        return _start_online_payment(order, request, db)
    except Exception:
        order.payment_status = "failed"
        sync_stock_after_payment(db, order)
        db.commit()
        flash(request, "Не вдалося відкрити онлайн-оплату. Резерв звільнено; перевірте налаштування LiqPay/ПриватБанк або резервного Monobank acquiring.", "error")
        return RedirectResponse(f"/order/{number}/success", status_code=303)


@app.get("/payments/liqpay/{number}", response_class=HTMLResponse)
def liqpay_payment_start(number: str, request: Request, db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.number == number).options(selectinload(Order.items)))
    if not order:
        raise HTTPException(status_code=404)
    if not _can_access_order(request, db, order):
        raise HTTPException(status_code=403)
    if order.payment_method != "online" or order.payment_status == "paid":
        return RedirectResponse(f"/order/{number}/success", status_code=303)

    if not liqpay_configured():
        if monobank_configured():
            try:
                return _start_monobank_payment(order, request, db)
            except Exception:
                pass
        order.payment_status = "failed"
        sync_stock_after_payment(db, order)
        db.commit()
        flash(request, "LiqPay не налаштовано, а резервний Monobank недоступний. Резерв товару звільнено.", "error")
        return RedirectResponse(f"/order/{number}/success", status_code=303)

    base = _public_base_url(request)
    try:
        checkout = create_liqpay_checkout(
            order_id=order.number,
            amount=order.total,
            description=f"Оплата замовлення TopBearing {order.number}",
            result_url=f"{base}/payment/return?provider=liqpay",
            server_url=f"{base}/payments/liqpay/webhook",
        )
        order.payment_status = "pending"
        db.commit()
        return HTMLResponse(
            _liqpay_checkout_html(checkout.action_url, checkout.data, checkout.signature),
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        # LiqPay is primary, but Mono is intentionally preserved as a fallback.
        if monobank_configured():
            try:
                return _start_monobank_payment(order, request, db)
            except Exception:
                pass
        order.payment_status = "failed"
        sync_stock_after_payment(db, order)
        db.commit()
        flash(request, "Не вдалося відкрити LiqPay, а резервна оплата Monobank також недоступна. Резерв товару звільнено.", "error")
        return RedirectResponse(f"/order/{number}/success", status_code=303)


@app.get("/payment/return", name="payment_return")
def payment_return(request: Request, db: Session = Depends(get_db)):
    order_id = request.session.get("last_order_id")
    order = db.get(Order, int(order_id)) if order_id else None
    if not order:
        return RedirectResponse("/account", status_code=303)

    provider = request.query_params.get("provider", "").strip().lower()
    if provider == "liqpay" and liqpay_configured():
        try:
            data = liqpay_payment_status(order.number)
            # A signed server callback remains authoritative. This status check only
            # improves the user experience when the callback and browser redirect race.
            _validate_liqpay_order_payload(
                order,
                data,
                require_amount=str(data.get("status", "")).lower() in {"success", "reversed"},
            )
            apply_liqpay_payment_event(order, data)
            order = db.scalar(select(Order).where(Order.id == order.id).options(selectinload(Order.items)))
            sync_stock_after_payment(db, order)
            db.commit()
        except Exception:
            pass
    elif order.mono_invoice_id and monobank_configured():
        try:
            data = invoice_status(order.mono_invoice_id)
            apply_payment_event(order, data)
            order = db.scalar(select(Order).where(Order.id == order.id).options(selectinload(Order.items)))
            sync_stock_after_payment(db, order)
            db.commit()
        except Exception:
            pass
    return RedirectResponse(f"/order/{order.number}/success", status_code=303)


@app.post("/payments/liqpay/webhook")
async def liqpay_webhook(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data_value = str(form.get("data", ""))
    signature = str(form.get("signature", ""))
    if not data_value or not signature:
        raise HTTPException(status_code=400, detail="Missing LiqPay callback data")
    try:
        data = verify_liqpay_callback(data_value, signature)
    except (LiqPayError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid LiqPay callback")

    number = str(data.get("order_id", "")).strip()
    order = db.scalar(select(Order).where(Order.number == number)) if number else None
    if not order:
        # Return OK so LiqPay does not repeatedly retry a callback for an unknown order.
        return JSONResponse({"ok": True})

    try:
        _validate_liqpay_order_payload(
            order,
            data,
            require_amount=str(data.get("status", "")).lower() in {"success", "reversed"},
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="LiqPay payment data mismatch")

    apply_liqpay_payment_event(order, data)
    order = db.scalar(select(Order).where(Order.id == order.id).options(selectinload(Order.items)))
    sync_stock_after_payment(db, order)
    db.commit()
    return JSONResponse({"ok": True})


@app.post("/payments/monobank/webhook")
async def monobank_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not verify_webhook(raw, request.headers.get("x-sign")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    data = parse_webhook(raw)
    order = None
    if data.get("invoiceId"):
        order = db.scalar(select(Order).where(Order.mono_invoice_id == data["invoiceId"]))
    if not order and data.get("reference"):
        order = db.scalar(select(Order).where(Order.number == data["reference"]))
    if order:
        apply_payment_event(order, data)
        order = db.scalar(select(Order).where(Order.id == order.id).options(selectinload(Order.items)))
        sync_stock_after_payment(db, order)
        db.commit()
    return JSONResponse({"ok": True})


@app.get("/order/{number}/success", response_class=HTMLResponse)
def order_success(number: str, request: Request, db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.number == number).options(selectinload(Order.items)))
    if not order:
        raise HTTPException(status_code=404)
    user = current_user(request, db)
    allowed = request.session.get("last_order_id") == order.id or (user and (user.role == "admin" or order.user_id == user.id))
    if not allowed:
        raise HTTPException(status_code=403)
    return render(request, db, "order_success.html", order=order)


# --------------------------- Admin ---------------------------


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    product_count = db.scalar(select(func.count(Product.id)).where(Product.is_active.is_(True))) or 0
    new_orders = db.scalar(select(func.count(Order.id)).where(Order.status == "new")) or 0
    unpaid = db.scalar(select(func.count(Order.id)).where(Order.payment_status.in_(["unpaid", "awaiting_payment", "failed"]))) or 0
    return render(request, db, "admin/dashboard.html", admin=admin, product_count=product_count, new_orders=new_orders, unpaid=unpaid)


@app.get("/admin/categories", response_class=HTMLResponse)
def admin_categories(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    counts = dict(
        db.execute(select(Product.category_id, func.count(Product.id)).group_by(Product.category_id)).all()
    )
    return render(request, db, "admin/categories.html", category_product_counts=counts)


@app.get("/admin/categories/new", response_class=HTMLResponse)
def admin_category_new(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return render(request, db, "admin/category_form.html", category=None, form_data={})


@app.get("/admin/categories/{category_id}/edit", response_class=HTMLResponse)
def admin_category_edit(category_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404)
    return render(request, db, "admin/category_form.html", category=category, form_data={})


def _category_parent_is_valid(db: Session, category: Category | None, parent: Category | None) -> bool:
    if not category or not parent:
        return True
    if category.id == parent.id:
        return False
    descendants = set(category_descendant_ids(db, category, active_only=False))
    return parent.id not in descendants


@app.post("/admin/categories/save")
async def admin_category_save(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)
    category_id = as_int(str(form.get("category_id", "")))
    category = db.get(Category, category_id) if category_id else None
    if category_id and not category:
        raise HTTPException(status_code=404)

    name = str(form.get("name", "")).strip()
    requested_code = str(form.get("code", "")).strip()
    parent_id = as_int(str(form.get("parent_id", "")))
    parent = db.get(Category, parent_id) if parent_id else None
    product_type = normalize_category_code(str(form.get("product_type", "")).strip()) or "generic"
    errors: list[str] = []
    if len(name) < 2:
        errors.append("Вкажіть назву категорії.")
    if parent_id and not parent:
        errors.append("Батьківську категорію не знайдено.")
    if not _category_parent_is_valid(db, category, parent):
        errors.append("Категорію не можна помістити всередину самої себе або її підкатегорії.")
    if product_type not in PRODUCT_TYPE_LABELS:
        errors.append("Невідомий тип характеристик товару.")
    if parent:
        product_type = category_product_type(parent)

    code = category.code if category else make_unique_category_code(db, name, requested_code=requested_code or None)
    if not category and requested_code:
        existing = db.scalar(select(Category).where(Category.code == slugify(requested_code, max_length=60)))
        if existing:
            errors.append("Категорія з таким кодом уже існує.")

    if errors:
        return render(
            request,
            db,
            "admin/category_form.html",
            status_code=400,
            category=category,
            errors=errors,
            form_data=dict(form),
        )

    is_new = category is None
    if category is None:
        category = Category(code=code, name=name)
        db.add(category)
        db.flush()
    category.name = name
    category.description = str(form.get("description", "")).strip() or None
    category.parent_id = parent.id if parent else None
    category.product_type = product_type
    category.sort_order = as_int(str(form.get("sort_order", "100")), 100) or 100
    category.is_active = form.get("is_active") == "1"
    category.show_in_menu = form.get("show_in_menu") == "1"
    category.require_prepayment = form.get("require_prepayment") == "1"
    category.cod_allowed = form.get("cod_allowed") == "1"
    audit(db, admin, "category_create" if is_new else "category_update", "category", category.id, category.name)
    db.commit()
    flash(request, "Категорію збережено.", "success")
    return RedirectResponse("/admin/categories", status_code=303)


@app.post("/admin/categories/{category_id}/toggle")
async def admin_category_toggle(category_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404)
    category.is_active = not category.is_active
    audit(db, admin, "category_toggle", "category", category.id, f"active={category.is_active}")
    db.commit()
    return RedirectResponse("/admin/categories", status_code=303)


@app.post("/admin/categories/{category_id}/delete")
async def admin_category_delete(category_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404)
    has_products = bool(db.scalar(select(Product.id).where(Product.category_id == category.id).limit(1)))
    has_children = bool(db.scalar(select(Category.id).where(Category.parent_id == category.id).limit(1)))
    if has_products or has_children:
        flash(request, "Спочатку перенесіть товари та підкатегорії. Непорожню категорію видалити не можна.", "error")
        return RedirectResponse("/admin/categories", status_code=303)
    audit(db, admin, "category_delete", "category", category.id, category.name)
    db.delete(category)
    db.commit()
    flash(request, "Категорію видалено.", "success")
    return RedirectResponse("/admin/categories", status_code=303)


@app.get("/admin/products", response_class=HTMLResponse)
def admin_products(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    params = request.query_params
    q = (params.get("q") or "").strip()
    category_id = as_int(params.get("category"))
    status = (params.get("status") or "all").strip()
    sort = (params.get("sort") or "newest").strip()
    page = max(1, as_int(params.get("page"), 1) or 1)
    per_page = as_int(params.get("per_page"), 50) or 50
    if per_page not in {25, 50, 100, 200}:
        per_page = 50

    stmt = select(Product)
    if q:
        for term in [item for item in re.split(r"\s+", q) if item]:
            pattern = f"%{term.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Product.name).like(pattern),
                    func.lower(Product.sku).like(pattern),
                    func.lower(func.coalesce(Product.manufacturer_code, "")).like(pattern),
                    func.lower(func.coalesce(Product.alternative_markings, "")).like(pattern),
                    func.lower(func.coalesce(Product.manufacturing_country, "")).like(pattern),
                    Product.brand.has(func.lower(Brand.name).like(pattern)),
                )
            )
    if category_id:
        selected_category = db.get(Category, category_id)
        if selected_category:
            stmt = stmt.where(Product.category_id.in_(category_descendant_ids(db, selected_category, active_only=False)))
    if status == "active":
        stmt = stmt.where(Product.is_active.is_(True))
    elif status == "hidden":
        stmt = stmt.where(Product.is_active.is_(False))

    if sort == "name_asc":
        stmt = stmt.order_by(Product.name.asc(), Product.id.desc())
    elif sort == "name_desc":
        stmt = stmt.order_by(Product.name.desc(), Product.id.desc())
    elif sort == "price_asc":
        stmt = stmt.order_by(Product.price.asc(), Product.id.desc())
    elif sort == "price_desc":
        stmt = stmt.order_by(Product.price.desc(), Product.id.desc())
    elif sort == "stock_asc":
        stmt = stmt.order_by(Product.stock_qty.asc(), Product.id.desc())
    elif sort == "stock_desc":
        stmt = stmt.order_by(Product.stock_qty.desc(), Product.id.desc())
    elif sort == "updated":
        stmt = stmt.order_by(Product.updated_at.desc(), Product.id.desc())
    else:
        stmt = stmt.order_by(Product.id.desc())

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    products = db.scalars(
        stmt.offset((page - 1) * per_page).limit(per_page).options(*_product_card_options())
    ).all()
    return render(
        request,
        db,
        "admin/products.html",
        products=products,
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        pagination_items=pagination_items(page, pages),
        admin_params=dict(params),
    )


@app.get("/admin/products/new", response_class=HTMLResponse)
def admin_product_new(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    brands = db.scalars(select(Brand).order_by(Brand.name)).all()
    return render(request, db, "admin/product_form.html", product=None, brands=brands)


@app.get("/admin/products/{product_id}/edit", response_class=HTMLResponse)
def admin_product_edit(product_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.brand),
            selectinload(Product.category),
            selectinload(Product.images),
            selectinload(Product.bearing_spec),
            selectinload(Product.belt_spec),
            selectinload(Product.seal_spec),
            selectinload(Product.lubricant_spec),
        )
    )
    if not product:
        raise HTTPException(status_code=404)
    brands = db.scalars(select(Brand).order_by(Brand.name)).all()
    return render(request, db, "admin/product_form.html", product=product, brands=brands)


def validate_product_form(form: Any, category: Category) -> list[str]:
    errors: list[str] = []
    kind = category_product_type(category)
    name = str(form.get("name", "")).strip()
    price = as_decimal(str(form.get("price", "")))
    if len(name) < 2:
        errors.append("Назва товару обов’язкова.")
    if price is None or price < 0:
        errors.append("Вкажіть коректну ціну.")

    if kind == "bearings":
        if any(as_decimal(str(form.get(key, ""))) is None for key in ("inner_diameter_mm", "outer_diameter_mm", "width_mm")):
            errors.append("Для підшипника обов’язкові внутрішній діаметр, зовнішній діаметр та ширина.")
    elif kind == "belts":
        if not str(form.get("profile", "")).strip() or as_decimal(str(form.get("length_mm", ""))) is None:
            errors.append("Для ременя обов’язкові профіль і довжина.")
    elif kind == "seals":
        if any(as_decimal(str(form.get(key, ""))) is None for key in ("seal_inner_diameter_mm", "seal_outer_diameter_mm", "seal_width_mm")):
            errors.append("Для сальника/манжети обов’язкові три основні розміри.")
    elif kind == "lubricants":
        if not str(form.get("lubricant_type", "")).strip() or not str(form.get("package_size", "")).strip():
            errors.append("Для змащення обов’язкові тип і фасування.")
        if len(str(form.get("description", "")).strip()) < 10:
            errors.append("Для змащення додайте короткий змістовний опис.")
    elif kind == "accessories":
        if len(str(form.get("description", "")).strip()) < 10:
            errors.append("Для аксесуара додайте короткий опис.")
    return errors


def set_product_spec(db: Session, product: Product, category: Category, form: Any) -> None:
    kind = category_product_type(category)
    # A product can be moved between categories in the admin panel. Remove an
    # old type-specific row so global searches cannot match stale dimensions.
    if kind != "bearings" and product.bearing_spec is not None:
        product.bearing_spec = None
    if kind != "belts" and product.belt_spec is not None:
        product.belt_spec = None
    if kind != "seals" and product.seal_spec is not None:
        product.seal_spec = None
    if kind != "lubricants" and product.lubricant_spec is not None:
        product.lubricant_spec = None

    if kind == "bearings":
        spec = product.bearing_spec or BearingSpec(product_id=product.id)
        spec.subtype = str(form.get("subtype", "")).strip() or None
        spec.inner_diameter_mm = as_decimal(str(form.get("inner_diameter_mm", "")))
        spec.outer_diameter_mm = as_decimal(str(form.get("outer_diameter_mm", "")))
        spec.width_mm = as_decimal(str(form.get("width_mm", "")))
        spec.rows = as_int(str(form.get("rows", "")))
        spec.rolling_element = str(form.get("rolling_element", "")).strip() or None
        spec.construction = str(form.get("construction", "")).strip() or None
        spec.series_type = str(form.get("series_type", "")).strip().upper() or None
        spec.cage_type = str(form.get("cage_type", "")).strip() or None
        spec.seal_type = str(form.get("bearing_seal_type", "")).strip() or None
        spec.clearance = str(form.get("clearance", "")).strip() or None
        spec.precision_class = str(form.get("precision_class", "")).strip() or None
        product.bearing_spec = spec
    elif kind == "belts":
        spec = product.belt_spec or BeltSpec(product_id=product.id)
        spec.belt_type = str(form.get("belt_type", "")).strip() or None
        spec.profile = normalize_belt_profile(str(form.get("profile", "")))
        spec.length_mm = as_decimal(str(form.get("length_mm", "")))
        spec.width_mm = as_decimal(str(form.get("belt_width_mm", "")))
        spec.ribs = as_int(str(form.get("ribs", "")))
        product.belt_spec = spec
    elif kind == "seals":
        spec = product.seal_spec or SealSpec(product_id=product.id)
        spec.seal_type = str(form.get("seal_type", "")).strip() or None
        spec.inner_diameter_mm = as_decimal(str(form.get("seal_inner_diameter_mm", "")))
        spec.outer_diameter_mm = as_decimal(str(form.get("seal_outer_diameter_mm", "")))
        spec.width_mm = as_decimal(str(form.get("seal_width_mm", "")))
        spec.material = str(form.get("material", "")).strip() or None
        spec.lip_type = str(form.get("lip_type", "")).strip() or None
        product.seal_spec = spec
    elif kind == "lubricants":
        spec = product.lubricant_spec or LubricantSpec(product_id=product.id)
        spec.lubricant_type = str(form.get("lubricant_type", "")).strip() or None
        spec.viscosity = str(form.get("viscosity", "")).strip() or None
        spec.base_type = str(form.get("base_type", "")).strip() or None
        spec.package_size = str(form.get("package_size", "")).strip() or None
        spec.temperature_range = str(form.get("temperature_range", "")).strip() or None
        product.lubricant_spec = spec


def save_upload(upload: UploadFile) -> str | None:
    if not upload or not upload.filename:
        return None
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Дозволені лише JPG, PNG та WEBP.")
    content = upload.file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Одне фото не може бути більшим за 5 МБ.")
    return save_product_image(content, UPLOAD_DIR)


@app.post("/admin/products/save")
async def admin_product_save(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)
    product_id = as_int(str(form.get("product_id", "")))
    product = db.get(Product, product_id) if product_id else None
    if product_id and not product:
        raise HTTPException(status_code=404)

    category_id = as_int(str(form.get("category_id", "")))
    category = db.get(Category, category_id) if category_id else None
    if not category:
        brands = db.scalars(select(Brand).order_by(Brand.name)).all()
        return render(request, db, "admin/product_form.html", status_code=400, product=product, brands=brands, errors=["Оберіть категорію."], form_data=dict(form))

    errors = validate_product_form(form, category)
    uploads = [f for f in form.getlist("images") if getattr(f, "filename", None)]
    existing_image_count = len(product.images) if product else 0
    delete_ids = {as_int(str(x)) for x in form.getlist("delete_image")}
    delete_ids.discard(None)
    url_lines = [line.strip() for line in str(form.get("image_urls", "")).splitlines() if line.strip()]
    projected = existing_image_count - len(delete_ids) + len(uploads) + len(url_lines)
    if projected > MAX_PRODUCT_IMAGES:
        errors.append(f"Максимум {MAX_PRODUCT_IMAGES} фото на товар.")

    if errors:
        brands = db.scalars(select(Brand).order_by(Brand.name)).all()
        return render(request, db, "admin/product_form.html", status_code=400, product=product, brands=brands, errors=errors, form_data=dict(form))

    brand = get_or_create_brand(
        db,
        str(form.get("brand_name", "")),
        str(form.get("brand_country", "")),
    )
    is_new = product is None
    if product is None:
        product = Product(
            sku=str(form.get("sku", "")).strip() or generate_sku(db, category.product_type),
            slug="temporary",
            name=str(form.get("name", "")).strip(),
            category_id=category.id,
            brand_id=brand.id if brand else None,
            price=as_decimal(str(form.get("price", "")), Decimal("0.00")) or Decimal("0.00"),
        )
        db.add(product)
        db.flush()
    else:
        requested_sku = str(form.get("sku", "")).strip()
        if requested_sku:
            duplicate = db.scalar(select(Product).where(Product.sku == requested_sku, Product.id != product.id))
            if duplicate:
                brands = db.scalars(select(Brand).order_by(Brand.name)).all()
                return render(request, db, "admin/product_form.html", status_code=400, product=product, brands=brands, errors=["Такий внутрішній код SKU уже існує."], form_data=dict(form))
            product.sku = requested_sku

    product.name = str(form.get("name", "")).strip()
    product.category_id = category.id
    product.brand_id = brand.id if brand else None
    product.manufacturer_code = str(form.get("manufacturer_code", "")).strip() or None
    product.alternative_markings = normalize_alternative_markings(
        str(form.get("alternative_markings", "")), product.manufacturer_code
    )
    product.manufacturing_country = str(form.get("manufacturing_country", "")).strip()[:120] or None
    product.price = as_decimal(str(form.get("price", "")), Decimal("0.00")) or Decimal("0.00")
    product.short_description = str(form.get("short_description", "")).strip() or None
    product.description = str(form.get("description", "")).strip() or None
    product.stock_is_tracked = form.get("stock_is_tracked") == "1"
    product.stock_qty = max(0, as_int(str(form.get("stock_qty", "0")), 0) or 0)
    product.availability_status = str(form.get("availability_status", "in_stock")) if not product.stock_is_tracked else ("in_stock" if product.stock_qty > 0 else "out_of_stock")
    product.is_active = form.get("is_active") == "1"
    product.is_featured = form.get("is_featured") == "1"
    prepayment_override = str(form.get("require_prepayment_override", "")).strip()
    cod_override = str(form.get("cod_allowed_override", "")).strip()
    product.require_prepayment_override = True if prepayment_override == "1" else (False if prepayment_override == "0" else None)
    product.cod_allowed_override = True if cod_override == "1" else (False if cod_override == "0" else None)

    requested_slug = str(form.get("seo_slug", "")).strip()
    if is_new:
        product.slug = make_unique_product_slug(
            db,
            product.name,
            brand.name if brand else None,
            product.manufacturer_code,
            product_id=product.id,
            requested_slug=requested_slug or None,
        )
    elif requested_slug and requested_slug != product.slug:
        old_slug = product.slug
        product.slug = make_unique_product_slug(
            db,
            product.name,
            brand.name if brand else None,
            product.manufacturer_code,
            product_id=product.id,
            requested_slug=requested_slug,
        )
        remember_slug_redirect(db, product, old_slug)
    set_product_spec(db, product, category, form)

    for image in list(product.images):
        if image.id in delete_ids:
            product.images.remove(image)

    next_sort = max([img.sort_order for img in product.images], default=-1) + 1
    for url in url_lines:
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("/static/")):
            continue
        product.images.append(ProductImage(url=url, alt_text=product.name, sort_order=next_sort))
        next_sort += 1
    for upload in uploads:
        try:
            url = save_upload(upload)
        except ValueError as exc:
            db.rollback()
            brands = db.scalars(select(Brand).order_by(Brand.name)).all()
            return render(request, db, "admin/product_form.html", status_code=400, product=product if not is_new else None, brands=brands, errors=[str(exc)], form_data=dict(form))
        if url:
            product.images.append(ProductImage(url=url, alt_text=product.name, sort_order=next_sort))
            next_sort += 1

    for index, image in enumerate(sorted(product.images, key=lambda x: (x.sort_order, x.id or 0))):
        image.sort_order = index
        image.is_primary = index == 0

    audit(db, admin, "product_create" if is_new else "product_update", "product", product.id, product.name)
    db.commit()
    flash(request, "Товар збережено.", "success")
    return RedirectResponse("/admin/products", status_code=303)


@app.post("/admin/products/{product_id}/toggle")
async def admin_product_toggle(product_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    product.is_active = not product.is_active
    audit(db, admin, "product_toggle", "product", product.id, f"active={product.is_active}")
    db.commit()
    return RedirectResponse("/admin/products", status_code=303)


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    status = request.query_params.get("status")
    stmt = select(Order).order_by(Order.id.desc()).options(selectinload(Order.items))
    if status in ORDER_STATUS_LABELS:
        stmt = stmt.where(Order.status == status)
    orders = db.scalars(stmt).all()
    return render(request, db, "admin/orders.html", orders=orders, active_status=status)


@app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
def admin_order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    order = db.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.items).selectinload(OrderItem.product)))
    if not order:
        raise HTTPException(status_code=404)
    return render(request, db, "admin/order_detail.html", order=order)


def _restore_order_stock(order: Order, db: Session) -> None:
    release_order_stock(db, order)


def _reserve_order_stock_again(order: Order, db: Session) -> bool:
    return re_reserve_order_stock(db, order)


@app.post("/admin/orders/{order_id}/update")
async def admin_order_update(order_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)
    order = db.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.items)))
    if not order:
        raise HTTPException(status_code=404)
    new_status = str(form.get("status", order.status))
    if new_status not in ORDER_STATUS_LABELS:
        raise HTTPException(status_code=400)

    if new_status == "cancelled" and order.status != "cancelled":
        _restore_order_stock(order, db)
    elif order.status == "cancelled" and new_status != "cancelled":
        if not _reserve_order_stock_again(order, db):
            flash(request, "Не можна повернути замовлення з скасованого статусу: недостатній залишок одного з товарів.", "error")
            return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)

    order.status = new_status
    if "tracking_number" in form:
        order.tracking_number = str(form.get("tracking_number", "")).strip() or None
    if order.payment_method != "online":
        payment_status = str(form.get("payment_status", order.payment_status))
        if payment_status in PAYMENT_STATUS_LABELS:
            order.payment_status = payment_status
    audit(db, admin, "order_update", "order", order.id, f"status={order.status}; payment={order.payment_status}")
    db.commit()
    flash(request, "Замовлення оновлено.", "success")
    return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)


@app.post("/admin/orders/{order_id}/refund")
async def admin_order_refund(order_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)

    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404)

    if order.payment_method != "online":
        flash(request, "Автоматичне повернення доступне лише для онлайн-оплати.", "error")
        return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)

    provider = (
        order.payment_provider
        or ("monobank" if order.mono_invoice_id else "liqpay")
    ).strip().lower()
    if provider != "liqpay":
        flash(
            request,
            "Це замовлення оплачувалось не через LiqPay. Автоматичний LiqPay refund для нього недоступний.",
            "error",
        )
        return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)

    if order.payment_status != "paid":
        flash(request, "Повернення можна запустити лише для замовлення зі статусом «Оплачено».", "error")
        return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)

    if not liqpay_configured():
        flash(
            request,
            "LiqPay не налаштований: перевірте LIQPAY_PUBLIC_KEY і LIQPAY_PRIVATE_KEY.",
            "error",
        )
        return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)

    try:
        result = liqpay_refund_payment(order.number, order.total)
    except (LiqPayError, ValueError) as exc:
        flash(request, f"LiqPay не прийняв повернення: {exc}", "error")
        return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)

    result_name = str(result.get("result", "")).strip().lower()
    status = str(result.get("status", "")).strip().lower()
    if result_name == "error" or status in {"error", "failure"}:
        description = str(
            result.get("err_description")
            or result.get("err_code")
            or "невідома помилка"
        )
        flash(request, f"LiqPay не прийняв повернення: {description}", "error")
        return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)

    order.payment_provider = "liqpay"
    if status == "reversed":
        order.payment_status = "refunded"
        order.refunded_at = datetime.utcnow()
        message = "Кошти повернено через LiqPay."
    else:
        order.payment_status = "refund_pending"
        message = "Запит на повернення передано LiqPay. Очікуємо підтвердження."

    audit(
        db,
        admin,
        "order_refund",
        "order",
        order.id,
        f"provider=liqpay; amount={order.total}; status={status or result_name}",
    )
    db.commit()
    flash(request, message, "success")
    return RedirectResponse(f"/admin/orders/{order.id}", status_code=303)


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return render(request, db, "admin/settings.html", store_settings=_settings(db))


@app.post("/admin/settings")
async def admin_settings_save(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    form = await request.form()
    verify_csrf(request, form)
    settings = _settings(db)
    settings.cod_enabled = form.get("cod_enabled") == "1"
    settings.cod_min_total = max(Decimal("0.00"), as_decimal(str(form.get("cod_min_total", "0")), Decimal("0.00")) or Decimal("0.00"))
    settings.online_payment_enabled = form.get("online_payment_enabled") == "1"
    settings.bank_transfer_enabled = form.get("bank_transfer_enabled") == "1"
    settings.contact_phone = str(form.get("contact_phone", "")).strip() or None
    settings.contact_email = str(form.get("contact_email", "")).strip() or None
    settings.contact_address = str(form.get("contact_address", "")).strip() or None
    settings.contact_telegram = str(form.get("contact_telegram", "")).strip()[:160] or None
    settings.contact_viber = str(form.get("contact_viber", "")).strip()[:160] or None
    settings.shipping_notice = str(form.get("shipping_notice", "")).strip() or "Відправка замовлень відбувається протягом 1–3 робочих днів."
    audit(db, admin, "settings_update", "store_settings", 1)
    db.commit()
    flash(request, "Налаштування збережено.", "success")
    return RedirectResponse("/admin/settings", status_code=303)
