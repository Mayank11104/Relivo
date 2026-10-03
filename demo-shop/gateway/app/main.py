import os
import json
import logging
from fastapi import FastAPI, HTTPException, Request
import httpx

app = FastAPI(title="API Gateway")

CATALOG_URL = os.getenv("CATALOG_URL", "http://catalog-service:8000")
ORDER_URL = os.getenv("ORDER_URL", "http://order-service:8000")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": "gateway"
        }
        if isinstance(record.msg, dict):
            log_record.update(record.msg)
        else:
            log_record["message"] = record.getMessage()
            if hasattr(record, "extra_info"):
                log_record.update(record.extra_info)
        return json.dumps(log_record)

logger = logging.getLogger("gateway")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway", "type": "liveness"}

@app.get("/ready")
def ready():
    return {"status": "ok", "service": "gateway", "type": "readiness"}

@app.get("/products")
async def get_products():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{CATALOG_URL}/products")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.error({"event": "catalog_request_failed", "error": str(e)})
            raise HTTPException(status_code=502, detail="Catalog service unavailable")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail="Catalog service error")

@app.get("/products/{product_id}")
async def get_product(product_id: int):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{CATALOG_URL}/products/{product_id}")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Product not found")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.error({"event": "catalog_request_failed", "error": str(e), "product_id": product_id})
            raise HTTPException(status_code=502, detail="Catalog service unavailable")

@app.post("/orders")
async def create_order(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(f"{ORDER_URL}/orders", json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json())
            return resp.json()
        except httpx.RequestError as e:
            logger.error({"event": "order_request_failed", "error": str(e)})
            raise HTTPException(status_code=502, detail="Order service unavailable")

@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{ORDER_URL}/orders/{order_id}")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Order not found")
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as e:
            logger.error({"event": "order_request_failed", "error": str(e), "order_id": order_id})
            raise HTTPException(status_code=502, detail="Order service unavailable")
