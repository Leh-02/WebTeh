from __future__ import annotations
import os
import httpx

API_URL = "https://api.novaposhta.ua/v2.0/json/"

def configured() -> bool:
    return bool(os.getenv("NOVA_POSHTA_API_KEY", "").strip())

async def _call(model: str, method: str, properties: dict) -> list[dict]:
    key = os.getenv("NOVA_POSHTA_API_KEY", "").strip()
    if not key:
        return []
    payload = {"apiKey": key, "modelName": model, "calledMethod": method, "methodProperties": properties}
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.post(API_URL, json=payload)
        response.raise_for_status()
        data = response.json()
    return list(data.get("data") or []) if data.get("success") else []

async def search_cities(query: str, limit: int = 20) -> list[dict]:
    query = (query or "").strip()
    if len(query) < 2:
        return []
    rows = await _call("AddressGeneral", "getSettlements", {
        "FindByString": query, "Limit": str(max(1, min(limit, 50))), "Page": "1"
    })
    return [{"ref": r.get("Ref"), "name": r.get("Description"),
             "region": r.get("RegionsDescription") or r.get("AreaDescription")} for r in rows]

async def search_warehouses(city_ref: str, query: str = "", limit: int = 50) -> list[dict]:
    city_ref = (city_ref or "").strip()
    if not city_ref:
        return []
    props = {"SettlementRef": city_ref, "Limit": str(max(1, min(limit, 100))), "Page": "1"}
    if query.strip():
        props["FindByString"] = query.strip()
    rows = await _call("AddressGeneral", "getWarehouses", props)
    return [{"ref": r.get("Ref"), "number": r.get("Number"), "name": r.get("Description"),
             "short_address": r.get("ShortAddress")} for r in rows]
