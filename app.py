"""
FastAPI Application for NoSQL E-Commerce Product and Customer Analytics System.
"""

import os
import json
import time
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.database import db
from backend.seed_data import generate_ecommerce_data, uuid_mock
from backend.analytics_engine import AnalyticsEngine
from backend.models import (
    ProductItem, ProductUpdate,
    CustomerItem, CustomerUpdate,
    OrderCreate, OrderStatusUpdate,
    NoSQLQueryRequest, MongoConnectRequest
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="NoSQL E-Commerce Product & Customer Analytics System",
    description="Enterprise Analytics & Management Dashboard powered by MongoDB & BSON Document Engine",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- SYSTEM & DB ENDPOINTS ----------------- #

@app.get("/api/status")
def get_system_status():
    """Retrieve database connectivity mode, document counts, and system metrics."""
    return {
        "status": "online",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db.status()
    }

@app.post("/api/db/connect")
def connect_mongodb(req: MongoConnectRequest):
    """Switch connection to an external MongoDB instance or Atlas."""
    success = db.connect(req.uri)
    if not success:
        return {
            "success": False,
            "message": "Could not connect to MongoDB server with provided URI. Remaining in embedded NoSQL engine mode.",
            "status": db.status()
        }
    return {
        "success": True,
        "message": f"Successfully connected to MongoDB ({req.uri})!",
        "status": db.status()
    }

@app.post("/api/db/seed")
def seed_database(order_count: int = 150):
    """Reset and generate fresh realistic e-commerce datasets."""
    data = generate_ecommerce_data(num_orders=order_count)
    if db.mode == "local":
        db.local_store.reset_data(data)
    else:
        # Remote MongoDB
        for coll_name, docs in data.items():
            coll = db.get_collection(coll_name)
            coll.delete_many({})
            if docs:
                coll.insert_many(docs)
    return {
        "success": True,
        "message": f"Database seeded successfully with {len(data['customers'])} customers, {len(data['products'])} products, and {len(data['orders'])} orders.",
        "counts": db.status()["counts"]
    }

@app.get("/api/db/export")
def export_database():
    """Export complete NoSQL dataset as JSON."""
    export_payload = {}
    for c in ["customers", "products", "orders", "transactions", "analytics_logs"]:
        coll = db.get_collection(c)
        export_payload[c] = list(coll.find({}))
    return JSONResponse(
        content=export_payload,
        headers={"Content-Disposition": "attachment; filename=ecommerce_nosql_export.json"}
    )

@app.get("/api/report/pdf")
def download_pdf_report():
    """Download the comprehensive project documentation PDF report."""
    pdf_path = BASE_DIR / "E-Commerce_Analytics_System_Report.pdf"
    if pdf_path.exists():
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename="E-Commerce_Analytics_System_Report.pdf"
        )
    raise HTTPException(status_code=404, detail="PDF report not found. Run generate_pdf.py first.")

# ----------------- ANALYTICS & INSIGHTS ----------------- #

@app.get("/api/analytics/kpis")
def get_executive_kpis(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category: Optional[str] = None
):
    """Compute executive-level business metrics via aggregation."""
    return AnalyticsEngine.get_executive_kpis(date_from=date_from, date_to=date_to, category=category)

@app.get("/api/analytics/sales-trend")
def get_sales_trend(period: str = "daily"):
    """Time-series revenue & order volume trend analysis."""
    return AnalyticsEngine.get_sales_trend(period=period)

@app.get("/api/analytics/categories")
def get_category_breakdown():
    """Category contribution pipeline."""
    return AnalyticsEngine.get_category_breakdown()

@app.get("/api/analytics/top-products")
def get_top_products(limit: int = 8):
    """Top selling and revenue-generating products."""
    return AnalyticsEngine.get_top_products(limit=limit)

@app.get("/api/analytics/customer-segmentation")
def get_customer_segmentation():
    """RFM customer segmentation breakdown and loyalty distribution."""
    return AnalyticsEngine.get_customer_segmentation()

@app.get("/api/analytics/payments-risk")
def get_payments_and_risk():
    """Payment gateways share, transaction volumes, and fraud risk scores."""
    return AnalyticsEngine.get_payment_and_risk_stats()

@app.get("/api/analytics/geo")
def get_geo_distribution():
    """Geographic revenue distribution by customer location."""
    return AnalyticsEngine.get_geo_distribution()

@app.get("/api/analytics/channels")
def get_channel_performance():
    """Sales and AOV breakdown by sales channel."""
    return AnalyticsEngine.get_channel_performance()

# ----------------- PRODUCTS CRUD ----------------- #

@app.get("/api/products")
def list_products(
    category: Optional[str] = None,
    search: Optional[str] = None,
    low_stock: Optional[bool] = None,
    sort_by: Optional[str] = "total_revenue",
    order: Optional[str] = "desc"
):
    """Search and filter product catalog."""
    query = {}
    if category and category != "All":
        query["category"] = category
    if search:
        query["$or"] = [
            {"title": {"$regex": search}},
            {"sku": {"$regex": search}}
        ]
    if low_stock:
        query["stock_quantity"] = {"$lte": 25}

    coll = db.get_collection("products")
    sort_dir = -1 if order == "desc" else 1
    docs = coll.find(query, sort=[(sort_by, sort_dir)])
    return docs

@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    coll = db.get_collection("products")
    p = coll.find_one({"$or": [{"product_id": product_id}, {"_id": product_id}]})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return p

@app.post("/api/products")
def create_product(item: ProductItem):
    coll = db.get_collection("products")
    now = datetime.now(timezone.utc).isoformat()
    pid = item.product_id or f"PRD-{random.randint(1100, 9999)}"
    margin = round(((item.price - item.cost_price) / item.price) * 100, 1) if item.price > 0 else 0.0

    doc = {
        "_id": pid,
        "product_id": pid,
        "title": item.title,
        "sku": item.sku,
        "category": item.category,
        "price": item.price,
        "cost_price": item.cost_price,
        "margin_percent": margin,
        "stock_quantity": item.stock_quantity,
        "reorder_threshold": item.reorder_threshold,
        "rating": 5.0,
        "review_count": 0,
        "is_active": item.is_active,
        "total_sales_count": 0,
        "total_revenue": 0.0,
        "created_at": now
    }
    inserted = coll.insert_one(doc)
    return inserted

@app.put("/api/products/{product_id}")
def update_product(product_id: str, updates: ProductUpdate):
    coll = db.get_collection("products")
    p = coll.find_one({"$or": [{"product_id": product_id}, {"_id": product_id}]})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    update_dict = {k: v for k, v in updates.dict(exclude_unset=True).items() if v is not None}
    
    # Recalculate margin if price or cost changed
    new_price = update_dict.get("price", p["price"])
    new_cost = update_dict.get("cost_price", p["cost_price"])
    if new_price > 0:
        update_dict["margin_percent"] = round(((new_price - new_cost) / new_price) * 100, 1)

    coll.update_one({"_id": p["_id"]}, {"$set": update_dict})
    return coll.find_one({"_id": p["_id"]})

@app.delete("/api/products/{product_id}")
def delete_product(product_id: str):
    coll = db.get_collection("products")
    deleted = coll.delete_one({"$or": [{"product_id": product_id}, {"_id": product_id}]})
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True, "message": "Product removed from catalog"}

# ----------------- CUSTOMERS CRUD ----------------- #

@app.get("/api/customers")
def list_customers(
    segment: Optional[str] = None,
    tier: Optional[str] = None,
    search: Optional[str] = None
):
    query = {}
    if segment and segment != "All":
        query["segment"] = segment
    if tier and tier != "All":
        query["loyalty_tier"] = tier
    if search:
        query["$or"] = [
            {"name": {"$regex": search}},
            {"email": {"$regex": search}},
            {"city": {"$regex": search}}
        ]
    coll = db.get_collection("customers")
    return coll.find(query, sort=[("total_spent", -1)])

@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: str):
    coll = db.get_collection("customers")
    c = coll.find_one({"$or": [{"customer_id": customer_id}, {"_id": customer_id}]})
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Fetch recent orders for customer via lookup
    orders_coll = db.get_collection("orders")
    orders = orders_coll.find({"customer_id": c["customer_id"]}, sort=[("order_date", -1)], limit=10)
    c["order_history"] = orders
    return c

@app.post("/api/customers")
def create_customer(item: CustomerItem):
    coll = db.get_collection("customers")
    cid = f"CUST-{random.randint(6000, 9999)}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "_id": cid,
        "customer_id": cid,
        "name": item.name,
        "email": item.email,
        "phone": item.phone or "+1 (555) 000-0000",
        "country": item.country,
        "city": item.city,
        "loyalty_tier": item.loyalty_tier,
        "segment": "New",
        "rfm": {"r": 5, "f": 1, "m": 1, "score": "511"},
        "total_spent": 0.0,
        "total_orders": 0,
        "last_order_date": None,
        "preferred_category": item.preferred_category,
        "registered_at": now
    }
    inserted = coll.insert_one(doc)
    return inserted

@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: str, updates: CustomerUpdate):
    coll = db.get_collection("customers")
    c = coll.find_one({"$or": [{"customer_id": customer_id}, {"_id": customer_id}]})
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    update_dict = {k: v for k, v in updates.dict(exclude_unset=True).items() if v is not None}
    coll.update_one({"_id": c["_id"]}, {"$set": update_dict})
    return coll.find_one({"_id": c["_id"]})

@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: str):
    coll = db.get_collection("customers")
    deleted = coll.delete_one({"$or": [{"customer_id": customer_id}, {"_id": customer_id}]})
    if not deleted:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"success": True, "message": "Customer profile removed"}

# ----------------- ORDERS & TRANSACTIONS ----------------- #

@app.get("/api/orders")
def list_orders(
    status: Optional[str] = None,
    channel: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = 100
):
    query = {}
    if status and status != "All":
        query["status"] = status
    if channel and channel != "All":
        query["channel"] = channel
    if customer_id:
        query["customer_id"] = customer_id

    coll = db.get_collection("orders")
    return coll.find(query, sort=[("order_date", -1)], limit=limit)

@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    coll = db.get_collection("orders")
    ord_doc = coll.find_one({"$or": [{"order_id": order_id}, {"_id": order_id}]})
    if not ord_doc:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Associated transaction
    txn_coll = db.get_collection("transactions")
    txn = txn_coll.find_one({"order_id": ord_doc["order_id"]})
    ord_doc["transaction"] = txn
    return ord_doc

@app.post("/api/orders")
def create_order(payload: OrderCreate):
    """Place a complete order: calculates totals, updates inventory, creates transaction, updates customer metrics."""
    cust_coll = db.get_collection("customers")
    prod_coll = db.get_collection("products")
    ord_coll = db.get_collection("orders")
    txn_coll = db.get_collection("transactions")

    cust = cust_coll.find_one({"$or": [{"customer_id": payload.customer_id}, {"_id": payload.customer_id}]})
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    order_items = []
    subtotal = 0.0
    total_cost = 0.0

    for it in payload.items:
        p = prod_coll.find_one({"$or": [{"product_id": it.product_id}, {"_id": it.product_id}]})
        if not p:
            raise HTTPException(status_code=400, detail=f"Product {it.product_id} not found")
        
        qty = max(1, it.quantity)
        disc = max(0, min(90, it.discount_percent)) / 100.0
        item_total = round(p["price"] * qty * (1.0 - disc), 2)
        
        order_items.append({
            "product_id": p["product_id"],
            "title": p["title"],
            "category": p["category"],
            "sku": p["sku"],
            "unit_price": p["price"],
            "cost_price": p["cost_price"],
            "quantity": qty,
            "discount_percent": int(disc * 100),
            "total": item_total
        })
        subtotal += item_total
        total_cost += round(p["cost_price"] * qty, 2)

        # Update product stock & sales count
        prod_coll.update_one(
            {"_id": p["_id"]},
            {
                "$inc": {
                    "stock_quantity": -qty,
                    "total_sales_count": qty,
                    "total_revenue": item_total
                }
            }
        )

    subtotal = round(subtotal, 2)
    tax = round(subtotal * 0.08, 2)
    shipping = 0.0 if subtotal > 100 else 9.99
    total_amount = round(subtotal + tax + shipping, 2)
    profit = round(subtotal - total_cost, 2)

    now_iso = datetime.now(timezone.utc).isoformat()
    oid = f"ORD-{random.randint(81000, 99999)}"
    tid = f"TXN-{random.randint(91000, 99999)}"

    order_doc = {
        "_id": oid,
        "order_id": oid,
        "customer_id": cust["customer_id"],
        "customer_name": cust["name"],
        "customer_email": cust["email"],
        "order_date": now_iso,
        "status": "Processing",
        "channel": payload.channel,
        "items": order_items,
        "item_count": sum(it["quantity"] for it in order_items),
        "subtotal": subtotal,
        "tax": tax,
        "shipping_fee": shipping,
        "total_amount": total_amount,
        "profit": profit,
        "shipping_address": {
            "city": payload.shipping_city or cust.get("city", "New York"),
            "country": payload.shipping_country or cust.get("country", "USA"),
            "postal_code": "10001"
        }
    }
    ord_coll.insert_one(order_doc)

    # Transaction
    risk_score = random.randint(1, 20)
    txn_doc = {
        "_id": tid,
        "transaction_id": tid,
        "order_id": oid,
        "customer_id": cust["customer_id"],
        "amount": total_amount,
        "currency": "USD",
        "payment_method": payload.payment_method,
        "status": "Success",
        "risk_score": risk_score,
        "gateway_reference": f"ch_{uuid_mock()}",
        "created_at": now_iso
    }
    txn_coll.insert_one(txn_doc)

    # Update customer stats
    cust_coll.update_one(
        {"_id": cust["_id"]},
        {
            "$inc": {"total_spent": total_amount, "total_orders": 1},
            "$set": {"last_order_date": now_iso}
        }
    )

    return {"success": True, "order": order_doc, "transaction": txn_doc}

@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: str, payload: OrderStatusUpdate):
    coll = db.get_collection("orders")
    updated = coll.update_one(
        {"$or": [{"order_id": order_id}, {"_id": order_id}]},
        {"$set": {"status": payload.status}}
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"success": True, "status": payload.status}

@app.get("/api/transactions")
def list_transactions(
    status: Optional[str] = None,
    method: Optional[str] = None,
    limit: int = 100
):
    query = {}
    if status and status != "All":
        query["status"] = status
    if method and method != "All":
        query["payment_method"] = method
    coll = db.get_collection("transactions")
    return coll.find(query, sort=[("created_at", -1)], limit=limit)

# ----------------- NOSQL QUERY & AGGREGATION PLAYGROUND ----------------- #

PRESET_PIPELINES = [
    {
        "id": "top_revenue_categories",
        "title": "Top Categories by Revenue ($unwind + $group + $sort)",
        "collection": "orders",
        "operation": "aggregate",
        "query": json.dumps([
            {"$unwind": "$items"},
            {
                "$group": {
                    "_id": "$items.category",
                    "total_revenue": {"$sum": "$items.total"},
                    "units_sold": {"$sum": "$items.quantity"},
                    "average_unit_price": {"$avg": "$items.unit_price"}
                }
            },
            {"$sort": {"total_revenue": -1}}
        ], indent=2)
    },
    {
        "id": "high_risk_transactions",
        "title": "Fraud Risk Monitoring ($match risk_score > 50)",
        "collection": "transactions",
        "operation": "find",
        "query": json.dumps({
            "risk_score": {"$gt": 50}
        }, indent=2)
    },
    {
        "id": "vip_customer_cohort",
        "title": "VIP High Value Customers ($match total_spent >= 1000)",
        "collection": "customers",
        "operation": "find",
        "query": json.dumps({
            "total_spent": {"$gte": 1000}
        }, indent=2)
    },
    {
        "id": "channel_profitability",
        "title": "Sales Channel Performance Pipeline",
        "collection": "orders",
        "operation": "aggregate",
        "query": json.dumps([
            {
                "$group": {
                    "_id": "$channel",
                    "gross_revenue": {"$sum": "$total_amount"},
                    "total_profit": {"$sum": "$profit"},
                    "order_count": {"$count": {}},
                    "avg_order_value": {"$avg": "$total_amount"}
                }
            },
            {"$sort": {"gross_revenue": -1}}
        ], indent=2)
    },
    {
        "id": "low_stock_critical",
        "title": "Low Stock Inventory Alerts ($lte 25)",
        "collection": "products",
        "operation": "find",
        "query": json.dumps({
            "stock_quantity": {"$lte": 25}
        }, indent=2)
    }
]

@app.get("/api/nosql/templates")
def get_query_templates():
    return PRESET_PIPELINES

@app.post("/api/nosql/execute")
def execute_nosql_query(req: NoSQLQueryRequest):
    """Dynamically parses and executes MongoDB find() or aggregate() pipelines."""
    start_time = time.time()
    coll = db.get_collection(req.collection)

    try:
        parsed = json.loads(req.query_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in query: {str(e)}")

    try:
        if req.operation == "aggregate":
            if not isinstance(parsed, list):
                raise ValueError("Aggregation pipeline must be a JSON array of pipeline stage objects.")
            results = coll.aggregate(parsed)
            # Cap results
            results = results[:req.limit]
        else: # find
            if not isinstance(parsed, dict):
                raise ValueError("Find query must be a JSON object representing the filter criteria.")
            results = coll.find(parsed, limit=req.limit)

        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "success": True,
            "operation": req.operation,
            "collection": req.collection,
            "execution_time_ms": duration_ms,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query Execution Error: {str(e)}")

# ----------------- STATIC FRONTEND ASSETS ----------------- #

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "E-Commerce Analytics System API is running. Frontend UI will be available at index.html."}
