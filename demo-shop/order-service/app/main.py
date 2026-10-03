import os
import json
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx
import asyncpg

app = FastAPI(title="Order Service")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/shop")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory-service:8000")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": "order-service"
        }
        if isinstance(record.msg, dict):
            log_record.update(record.msg)
        else:
            log_record["message"] = record.getMessage()
        return json.dumps(log_record)

logger = logging.getLogger("order")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class OrderRequest(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)

db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    except Exception as e:
        logger.error({"event": "db_pool_creation_failed", "error": str(e)})

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

@app.get("/health")
def health():
    return {"status": "ok", "service": "order", "type": "liveness"}

@app.get("/ready")
async def ready():
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database pool not initialized")
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok", "service": "order", "type": "readiness"}
    except Exception as e:
        logger.error({"event": "readiness_check_failed", "error": str(e)})
        raise HTTPException(status_code=503, detail="Database unavailable")

async def release_inventory(product_id: int, quantity: int):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                f"{INVENTORY_URL}/inventory/release",
                json={"product_id": product_id, "quantity": quantity}
            )
            resp.raise_for_status()
            logger.info({"event": "inventory_rollback_success", "product_id": product_id, "quantity": quantity})
        except Exception as e:
            logger.error({"event": "inventory_rollback_failed", "product_id": product_id, "quantity": quantity, "error": str(e)})

@app.post("/orders")
async def create_order(order: OrderRequest):
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    # 1. Reserve Inventory
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                f"{INVENTORY_URL}/inventory/reserve", 
                json={"product_id": order.product_id, "quantity": order.quantity}
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Product not found in inventory")
            if resp.status_code == 400:
                raise HTTPException(status_code=400, detail="Insufficient stock")
            resp.raise_for_status()
            logger.info({"event": "inventory_reserved", "product_id": order.product_id, "quantity": order.quantity})
        except HTTPException:
            raise
        except Exception as e:
            logger.error({"event": "inventory_reservation_failed", "error": str(e), "product_id": order.product_id})
            raise HTTPException(status_code=502, detail="Inventory service unavailable")
            
    # 2. Write to DB with Saga compensating transaction on failure
    try:
        async with db_pool.acquire() as conn:
            # Check if product exists physically to prevent foreign key violation if catalog not in sync with inventory
            row = await conn.fetchrow("SELECT id FROM products WHERE id = $1", order.product_id)
            if not row:
                raise asyncpg.ForeignKeyViolationError("Product does not exist")

            order_id = await conn.fetchval(
                "INSERT INTO orders (product_id, quantity, status) VALUES ($1, $2, $3) RETURNING id",
                order.product_id, order.quantity, "CREATED"
            )
            logger.info({"event": "order_created", "order_id": order_id, "product_id": order.product_id})
            return {"id": order_id, "status": "CREATED"}
    except asyncpg.ForeignKeyViolationError:
        logger.error({"event": "order_creation_failed_fk", "product_id": order.product_id})
        await release_inventory(order.product_id, order.quantity)
        raise HTTPException(status_code=400, detail="Invalid product_id")
    except Exception as e:
        logger.error({"event": "order_creation_failed", "error": str(e), "product_id": order.product_id})
        await release_inventory(order.product_id, order.quantity)
        raise HTTPException(status_code=503, detail="Database error during order creation")

@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
            if not row:
                raise HTTPException(status_code=404, detail="Order not found")
            
            data = dict(row)
            data['created_at'] = data['created_at'].isoformat() if data.get('created_at') else None
            return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "db_query_failed", "error": str(e), "order_id": order_id})
        raise HTTPException(status_code=503, detail="Database error")
