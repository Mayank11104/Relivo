import os
import json
import logging
from fastapi import FastAPI, HTTPException
import asyncpg

app = FastAPI(title="Catalog Service")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/shop")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": "catalog-service"
        }
        if isinstance(record.msg, dict):
            log_record.update(record.msg)
        else:
            log_record["message"] = record.getMessage()
        return json.dumps(log_record)

logger = logging.getLogger("catalog")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        logger.info({"event": "db_pool_created"})
    except Exception as e:
        logger.error({"event": "db_pool_creation_failed", "error": str(e)})

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()
        logger.info({"event": "db_pool_closed"})

@app.get("/health")
def health():
    return {"status": "ok", "service": "catalog", "type": "liveness"}

@app.get("/ready")
async def ready():
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database pool not initialized")
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok", "service": "catalog", "type": "readiness", "db": "connected"}
    except Exception as e:
        logger.error({"event": "readiness_check_failed", "error": str(e)})
        raise HTTPException(status_code=503, detail="Database connection failed")

@app.get("/products")
async def get_products():
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM products")
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error({"event": "db_query_failed", "error": str(e)})
        raise HTTPException(status_code=503, detail="Database error")

@app.get("/products/{product_id}")
async def get_product(product_id: int):
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
            if not row:
                raise HTTPException(status_code=404, detail="Product not found")
            return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "db_query_failed", "error": str(e), "product_id": product_id})
        raise HTTPException(status_code=503, detail="Database error")
