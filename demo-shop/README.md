# Demo Shop (Dummy Infrastructure for Relivo)

This is a purposefully small, multi-service application designed to act as the "dummy infrastructure" for testing the **Relivo** SRE & Security Multi-Agent system.

## Architecture

* **Gateway:** Entry point for REST APIs (FastAPI)
* **Catalog Service:** Manages products (FastAPI -> PostgreSQL)
* **Order Service:** Manages orders (FastAPI -> Inventory Service -> PostgreSQL)
* **Inventory Service:** Manages stock (FastAPI -> Redis)

## Endpoints

* `GET /products`
* `GET /products/{id}`
* `POST /orders` (Body: `{"product_id": 101, "quantity": 1}`)
* `GET /orders/{id}`
* `GET /health` (available on all services)

## How to Run Locally

```bash
docker compose up --build
```

The API Gateway will be available at `http://localhost:8000`.

## Purpose

By having interconnected dependencies (Gateway -> Order -> Inventory -> Redis), we can easily create simulated failures (e.g. killing the Redis container) to test how our Relivo agents investigate cascading failures.
