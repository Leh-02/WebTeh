from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="customer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    orders: Mapped[list[Order]] = relationship(back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    products: Mapped[list[Product]] = relationship(back_populates="category")


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True, nullable=False)

    products: Mapped[list[Product]] = relationship(back_populates="brand")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    manufacturer_code: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(220), index=True, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True, nullable=False)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), index=True, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # stock_qty stays non-null for compatibility. stock_is_tracked tells whether it should be used.
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stock_is_tracked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    availability_status: Mapped[str] = mapped_column(String(32), default="in_stock", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    category: Mapped[Category] = relationship(back_populates="products")
    brand: Mapped[Brand | None] = relationship(back_populates="products")
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order"
    )
    bearing_spec: Mapped[BearingSpec | None] = relationship(back_populates="product", uselist=False, cascade="all, delete-orphan")
    belt_spec: Mapped[BeltSpec | None] = relationship(back_populates="product", uselist=False, cascade="all, delete-orphan")
    seal_spec: Mapped[SealSpec | None] = relationship(back_populates="product", uselist=False, cascade="all, delete-orphan")
    lubricant_spec: Mapped[LubricantSpec | None] = relationship(back_populates="product", uselist=False, cascade="all, delete-orphan")

    @property
    def primary_image(self) -> str | None:
        if not self.images:
            return None
        for image in self.images:
            if image.is_primary:
                return image.url
        return self.images[0].url

    @property
    def storefront_availability(self) -> str:
        if self.stock_is_tracked:
            return "in_stock" if self.stock_qty > 0 else "out_of_stock"
        return self.availability_status or "in_stock"


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(600), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(220), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    product: Mapped[Product] = relationship(back_populates="images")


class BearingSpec(Base):
    __tablename__ = "bearing_specs"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    subtype: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inner_diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)
    outer_diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)
    rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cage_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    seal_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    clearance: Mapped[str | None] = mapped_column(String(80), nullable=True)
    precision_class: Mapped[str | None] = mapped_column(String(80), nullable=True)

    product: Mapped[Product] = relationship(back_populates="bearing_spec")


class BeltSpec(Base):
    __tablename__ = "belt_specs"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    belt_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    profile: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    length_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True, index=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)

    product: Mapped[Product] = relationship(back_populates="belt_spec")


class SealSpec(Base):
    __tablename__ = "seal_specs"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    seal_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inner_diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)
    outer_diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True, index=True)
    material: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lip_type: Mapped[str | None] = mapped_column(String(120), nullable=True)

    product: Mapped[Product] = relationship(back_populates="seal_spec")


class LubricantSpec(Base):
    __tablename__ = "lubricant_specs"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    lubricant_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    viscosity: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    base_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    package_size: Mapped[str | None] = mapped_column(String(120), nullable=True)
    temperature_range: Mapped[str | None] = mapped_column(String(160), nullable=True)

    product: Mapped[Product] = relationship(back_populates="lubricant_spec")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="new", index=True, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), default="unpaid", index=True, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stock_restored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    delivery_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    customer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    delivery_service: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivery_city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    delivery_branch: Mapped[str | None] = mapped_column(String(160), nullable=True)
    delivery_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(String(300), nullable=True)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(120), nullable=True)

    mono_invoice_id: Mapped[str | None] = mapped_column(String(120), unique=True, index=True, nullable=True)
    payment_event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    user: Mapped[User | None] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True, nullable=True)
    sku_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(220), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()


class StoreSettings(Base):
    __tablename__ = "store_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    cod_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cod_min_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=500, nullable=False)
    online_payment_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bank_transfer_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    contact_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contact_telegram: Mapped[str | None] = mapped_column(String(160), nullable=True)
    shipping_notice: Mapped[str] = mapped_column(String(240), default="Відправка замовлень відбувається протягом 1–3 робочих днів.", nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
