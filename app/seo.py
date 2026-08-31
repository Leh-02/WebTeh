from __future__ import annotations
import os
from decimal import Decimal
from html import escape
from urllib.parse import urljoin
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Category, Product

PRIVATE_PREFIXES = (
    "/admin","/account","/cart","/checkout","/login","/register","/forgot-password",
    "/reset-password","/favorites","/order/","/payment/","/payments/","/api/",
)

def public_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")

def _absolute(request: Request, value: str | None) -> str | None:
    if not value: return None
    if value.startswith(("http://", "https://")): return value
    return urljoin(public_base_url(request) + "/", value.lstrip("/"))

def _default_description() -> str:
    return "TopBearing — підшипники, пасові ремені, сальники, змащення та промислові комплектуючі з доставкою по Україні."

def default_seo_context(request: Request) -> dict:
    path, base = request.url.path, public_base_url(request)
    return {
        "seo_title": None, "seo_description": _default_description(),
        "canonical_url": f"{base}{path if path != '/' else '/'}",
        "robots_meta": "noindex,follow" if path.startswith(PRIVATE_PREFIXES) else "index,follow",
        "seo_json_ld": [], "og_image": None,
        "google_site_verification": os.getenv("GOOGLE_SITE_VERIFICATION", "").strip(),
        "ga4_measurement_id": os.getenv("GA4_MEASUREMENT_ID", "").strip(),
    }

def product_seo_context(request: Request, product: Product) -> dict:
    brand = product.brand.name if product.brand and product.brand.name != "Без бренду" else ""
    title = product.name + (f" {brand}" if brand and brand.casefold() not in product.name.casefold() else "")
    title += " — купити в Україні | TopBearing"
    description = (product.short_description or product.description or "").strip()
    if not description:
        details = ([f"маркування {product.manufacturer_code}"] if product.manufacturer_code else [])
        details += [f"ціна {Decimal(product.price):.2f} грн", "наявність та характеристики"]
        description = f"{product.name}. " + ", ".join(details) + ". Доставка по Україні."
    description = " ".join(description.split())[:300]
    base = public_base_url(request)
    url = f"{base}/product/{product.slug}"
    image = _absolute(request, product.primary_image)
    availability = {
        "in_stock":"https://schema.org/InStock",
        "out_of_stock":"https://schema.org/OutOfStock",
        "on_order":"https://schema.org/PreOrder",
    }.get(product.storefront_availability, "https://schema.org/InStock")
    product_ld = {
        "@context":"https://schema.org","@type":"Product","name":product.name,"sku":product.sku,
        "url":url,"description":description,
        "offers":{"@type":"Offer","url":url,"priceCurrency":"UAH","price":f"{Decimal(product.price):.2f}",
                  "availability":availability,"itemCondition":"https://schema.org/NewCondition"}
    }
    if product.manufacturer_code: product_ld["mpn"] = product.manufacturer_code
    if brand: product_ld["brand"] = {"@type":"Brand","name":brand}
    if image: product_ld["image"] = [image]
    category_url = f"{base}/catalog/{product.category.code}"
    breadcrumb = {
        "@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Головна","item":f"{base}/"},
            {"@type":"ListItem","position":2,"name":product.category.name or "Каталог","item":category_url},
            {"@type":"ListItem","position":3,"name":product.name,"item":url},
        ]
    }
    return {"seo_title":title,"seo_description":description,"canonical_url":url,
            "robots_meta":"index,follow","seo_json_ld":[product_ld,breadcrumb],"og_image":image}

def catalog_seo_context(request: Request, category: Category | None, *, has_filters: bool) -> dict:
    base = public_base_url(request)
    if category:
        title = f"{category.name or category.code} — купити в Україні | TopBearing"
        desc = (category.description or "").strip() or f"{category.name or category.code}: ціни, характеристики та наявність у TopBearing."
        canonical = f"{base}/catalog/{category.code}"
    else:
        title, desc, canonical = "Каталог підшипників, ременів і сальників | TopBearing", _default_description(), f"{base}/catalog"
    return {"seo_title":title,"seo_description":desc[:300],"canonical_url":canonical,
            "robots_meta":"noindex,follow" if has_filters else "index,follow"}

def robots_txt(request: Request) -> str:
    base = public_base_url(request)
    return "\n".join([
        "User-agent: *","Disallow: /admin","Disallow: /account","Disallow: /cart",
        "Disallow: /checkout","Disallow: /login","Disallow: /register","Disallow: /forgot-password",
        "Disallow: /reset-password","Disallow: /favorites","Disallow: /order/","Disallow: /payment/",
        "Disallow: /payments/","Disallow: /api/",f"Sitemap: {base}/sitemap.xml",""
    ])

def sitemap_xml(request: Request, db: Session) -> str:
    base = public_base_url(request)
    categories = db.scalars(select(Category).where(
        Category.is_active.is_(True), Category.products.any(Product.is_active.is_(True))
    ).order_by(Category.sort_order, Category.id)).all()
    products = db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.id)).all()
    rows = [(f"{base}/", None),(f"{base}/catalog", None)]
    rows += [(f"{base}/catalog/{c.code}", None) for c in categories]
    rows += [(f"{base}/product/{p.slug}", p.updated_at or p.created_at) for p in products]
    nodes = []
    for loc, lastmod in rows:
        node = f"<url><loc>{escape(loc)}</loc>"
        if lastmod: node += f"<lastmod>{lastmod.date().isoformat()}</lastmod>"
        nodes.append(node + "</url>")
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(nodes) + "</urlset>"


def merchant_feed_xml(request: Request, db: Session) -> str:
    """Google Merchant Center compatible RSS product feed."""
    base = public_base_url(request)
    products = db.scalars(
        select(Product).where(Product.is_active.is_(True)).order_by(Product.id)
    ).all()
    items = []
    for product in products:
        link = f"{base}/product/{product.slug}"
        description = " ".join(
            (product.short_description or product.description or product.name).split()
        )[:5000]
        availability = {
            "in_stock": "in_stock",
            "out_of_stock": "out_of_stock",
            "on_order": "preorder",
        }.get(product.storefront_availability, "in_stock")
        image = _absolute(request, product.primary_image)
        brand = product.brand.name if product.brand and product.brand.name != "Без бренду" else None
        node = [
            "<item>",
            f"<g:id>{escape(product.sku)}</g:id>",
            f"<title>{escape(product.name)}</title>",
            f"<description>{escape(description)}</description>",
            f"<link>{escape(link)}</link>",
            f"<g:availability>{availability}</g:availability>",
            f"<g:price>{Decimal(product.price):.2f} UAH</g:price>",
            "<g:condition>new</g:condition>",
        ]
        if image:
            node.append(f"<g:image_link>{escape(image)}</g:image_link>")
        if brand:
            node.append(f"<g:brand>{escape(brand)}</g:brand>")
        if product.manufacturer_code:
            node.append(f"<g:mpn>{escape(product.manufacturer_code)}</g:mpn>")
        node.append("</item>")
        items.append("".join(node))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0"><channel>'
        '<title>TopBearing</title>'
        f'<link>{escape(base)}</link>'
        '<description>TopBearing product feed</description>'
        + "".join(items)
        + "</channel></rss>"
    )
