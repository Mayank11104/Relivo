import os
import json
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import redis.asyncio as redis

app = FastAPI(title="Inventory Service")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": "inventory-service"
        }
        if isinstance(record.msg, dict):
            log_record.update(record.msg)
        else:
            log_record["message"] = record.getMessage()
        return json.dumps(log_record)

logger = logging.getLogger("inventory")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

r = None

class ReserveRequest(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)

RESERVE_LUA_SCRIPT = """
local stock = tonumber(redis.call('get', KEYS[1]))
local qty = tonumber(ARGV[1])
if stock == nil then
    return -1
end
if stock < qty then
    return -2
end
redis.call('decrby', KEYS[1], qty)
return stock - qty
"""

@app.on_event("startup")
async def startup_event():
    global r
    r = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)
    try:
        # Initialize some mock inventory if empty
        if not await r.exists("product:101"):
            await r.set("product:101", 50)
            await r.set("product:102", 12)
            await r.set("product:103", 0)
        logger.info({"event": "redis_connected"})
    except Exception as e:
        logger.error({"event": "redis_connection_failed", "error": str(e)})

@app.on_event("shutdown")
async def shutdown_event():
    if r:
        await r.aclose()

@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory", "type": "liveness"}

@app.get("/ready")
async def ready():
    try:
        await r.ping()
        return {"status": "ok", "service": "inventory", "type": "readiness", "redis": "connected"}
    except Exception as e:
        logger.error({"event": "readiness_check_failed", "error": str(e)})
        raise HTTPException(status_code=503, detail="Redis unavailable")

@app.get("/inventory/{product_id}")
async def get_inventory(product_id: int):
    try:
        val = await r.get(f"product:{product_id}")
        if val is None:
            raise HTTPException(status_code=404, detail="Product not found in inventory")
        return {"product_id": product_id, "stock": int(val)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "redis_query_failed", "error": str(e)})
        raise HTTPException(status_code=503, detail="Redis error")

@app.post("/inventory/reserve")
async def reserve_inventory(req: ReserveRequest):
    key = f"product:{req.product_id}"
    try:
        result = await r.eval(RESERVE_LUA_SCRIPT, 1, key, req.quantity)
        if result == -1:
            raise HTTPException(status_code=404, detail="Product not found in inventory")
        if result == -2:
            raise HTTPException(status_code=400, detail="Insufficient stock")
        
        logger.info({"event": "inventory_reserved", "product_id": req.product_id, "quantity": req.quantity, "remaining": result})
        return {"status": "reserved", "remaining": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "redis_reservation_failed", "error": str(e), "product_id": req.product_id})
        raise HTTPException(status_code=503, detail="Redis error")

@app.post("/inventory/release")
async def release_inventory(req: ReserveRequest):
    key = f"product:{req.product_id}"
    try:
        exists = await r.exists(key)
        if exists:
            await r.incrby(key, req.quantity)
            logger.info({"event": "inventory_released", "product_id": req.product_id, "quantity": req.quantity})
        return {"status": "released"}
    except Exception as e:
        logger.error({"event": "redis_release_failed", "error": str(e), "product_id": req.product_id})
        raise HTTPException(status_code=503, detail="Redis error")
