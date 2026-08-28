"""Import/update TopBearing products from CSV.

Expected UTF-8 columns (unused category-specific columns may be empty):
sku,name,category,brand,price,stock_qty,unit,description,image_url,
subtype,inner_diameter_mm,outer_diameter_mm,width_mm,rows,cage_type,seal_type,clearance,precision_class,
belt_type,profile,length_mm,belt_width_mm,
seal_material,lip_type,require_prepayment,cod_allowed

category codes: bearings, housed-bearings, belts, seals
Boolean overrides: blank=inherit, 1/true/yes=true, 0/false/no=false
"""
from __future__ import annotations
import csv, sys
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import SessionLocal
from app.models import Brand, Category, Product, BearingSpec, BeltSpec, SealSpec


def d(v):
    v=(v or '').strip().replace(',','.')
    return Decimal(v) if v else None

def b(v):
    v=(v or '').strip().lower()
    if not v: return None
    if v in {'1','true','yes','y','так'}: return True
    if v in {'0','false','no','n','ні'}: return False
    raise ValueError(f'Bad boolean: {v}')

def slug(v):
    import re
    s=re.sub(r'[^a-z0-9]+','-',v.lower()).strip('-')
    return s or 'brand'

if len(sys.argv) != 2:
    raise SystemExit('Usage: python scripts/import_products_csv.py products.csv')

path=Path(sys.argv[1])
db=SessionLocal(); created=updated=0
try:
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        for n,row in enumerate(csv.DictReader(f),start=2):
            sku=(row.get('sku') or '').strip()
            if not sku: raise ValueError(f'Row {n}: sku is required')
            cat=db.execute(select(Category).where(Category.code==(row.get('category') or '').strip())).scalar_one_or_none()
            if not cat: raise ValueError(f'Row {n}: unknown category')
            brand=None
            if (row.get('brand') or '').strip():
                name=row['brand'].strip()
                brand=db.execute(select(Brand).where(Brand.name==name)).scalar_one_or_none()
                if not brand:
                    base=slug(name); candidate=base; i=2
                    while db.execute(select(Brand.id).where(Brand.slug==candidate)).first(): candidate=f'{base}-{i}'; i+=1
                    brand=Brand(name=name,slug=candidate); db.add(brand); db.flush()
            p=db.execute(select(Product).where(Product.sku==sku)).scalar_one_or_none()
            is_new=p is None
            if is_new:
                p=Product(sku=sku,slug=sku.lower().replace(' ','-'),name=row.get('name') or sku,category_id=cat.id)
                db.add(p); db.flush(); created+=1
            else: updated+=1
            p.name=(row.get('name') or p.name).strip(); p.category_id=cat.id; p.brand_id=brand.id if brand else None
            p.price=d(row.get('price')) or Decimal('0'); p.stock_qty=int(row.get('stock_qty') or 0); p.unit=(row.get('unit') or 'шт').strip()
            p.description=(row.get('description') or '').strip(); p.image_url=(row.get('image_url') or p.image_url or '/static/img/product-placeholder.svg').strip()
            p.require_prepayment_override=b(row.get('require_prepayment')); p.cod_allowed_override=b(row.get('cod_allowed')); p.is_active=True
            if cat.code in {'bearings','housed-bearings'}:
                s=p.bearing_spec or BearingSpec(product_id=p.id)
                s.subtype=(row.get('subtype') or '').strip(); s.inner_diameter_mm=d(row.get('inner_diameter_mm')); s.outer_diameter_mm=d(row.get('outer_diameter_mm')); s.width_mm=d(row.get('width_mm'))
                s.rows=int(row['rows']) if (row.get('rows') or '').strip() else None; s.cage_type=(row.get('cage_type') or '').strip(); s.seal_type=(row.get('seal_type') or '').strip(); s.clearance=(row.get('clearance') or '').strip(); s.precision_class=(row.get('precision_class') or '').strip(); p.bearing_spec=s; p.belt_spec=None; p.seal_spec=None
            elif cat.code=='belts':
                s=p.belt_spec or BeltSpec(product_id=p.id); s.belt_type=(row.get('belt_type') or '').strip(); s.profile=(row.get('profile') or '').strip(); s.length_mm=d(row.get('length_mm')); s.width_mm=d(row.get('belt_width_mm')); p.belt_spec=s; p.bearing_spec=None; p.seal_spec=None
            elif cat.code=='seals':
                s=p.seal_spec or SealSpec(product_id=p.id); s.seal_type=(row.get('seal_type') or '').strip(); s.inner_diameter_mm=d(row.get('inner_diameter_mm')); s.outer_diameter_mm=d(row.get('outer_diameter_mm')); s.width_mm=d(row.get('width_mm')); s.material=(row.get('seal_material') or '').strip(); s.lip_type=(row.get('lip_type') or '').strip(); p.seal_spec=s; p.bearing_spec=None; p.belt_spec=None
    db.commit()
finally:
    db.close()
print(f'Imported: created={created}, updated={updated}')
