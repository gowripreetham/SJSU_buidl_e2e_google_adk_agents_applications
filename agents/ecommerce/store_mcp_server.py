"""MCP server (stdio) for a sports store, backed by SQLite.

This plays the role that "MCP Toolbox for Databases + AlloyDB" plays in the Google codelab: the agent never writes SQL,
it calls named, parameterised tools. Here the database is SQLite (STORE_DB) with a synthetic catalogue seeded on first run,
and product search is a small TF-IDF ranking instead of AlloyDB vector search.
Tools that act for a user take `user_email`; the ADK agent overwrites that argument from the signed-in session
(see agent.py) so the model cannot act for someone else.
"""
from __future__ import annotations
import json
import math
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

DB = Path(os.environ.get("STORE_DB", Path(__file__).parent / "store.db"))
mcp = FastMCP("sports-store")

PRODUCTS = [
    ("Trailblazer GTX", "Northpeak", "running shoes", 139.0, "Waterproof trail running shoe with deep lugs for mud and wet rock.", ["40", "41", "42", "43", "44"], ["Black/Lime", "Grey/Orange"]),
    ("Cloudstride 3", "Aerolite", "running shoes", 119.0, "Cushioned road running shoe for daily training and long runs.", ["38", "39", "40", "41", "42", "43"], ["White/Blue", "Black"]),
    ("Tempo Racer", "Aerolite", "running shoes", 159.0, "Lightweight carbon-plated racing shoe for 10k to marathon.", ["40", "41", "42", "43"], ["Neon Yellow"]),
    ("Summit Shell Jacket", "Northpeak", "jackets", 189.0, "Three-layer waterproof breathable shell for hiking in rain and wind.", ["S", "M", "L", "XL"], ["Red", "Navy"]),
    ("Breeze Run Jacket", "Aerolite", "jackets", 79.0, "Packable windproof running jacket with reflective details.", ["S", "M", "L"], ["Black", "Sky Blue"]),
    ("Court Pro Racket", "Vantage", "tennis", 199.0, "Control-oriented tennis racket, 305 g, 16x19 string pattern.", ["One Size"], ["White/Red"]),
    ("Match Tennis Balls 4-pack", "Vantage", "tennis", 9.5, "Pressurised all-court tennis balls.", ["One Size"], ["Yellow"]),
    ("Flex Yoga Mat 5mm", "Calma", "yoga", 39.0, "Non-slip 5 mm yoga mat with alignment lines.", ["One Size"], ["Sage", "Charcoal"]),
    ("Peak 30L Backpack", "Northpeak", "hiking", 109.0, "30 litre hiking backpack with rain cover and ventilated back panel.", ["One Size"], ["Olive", "Black"]),
    ("Ridge Trekking Poles", "Northpeak", "hiking", 69.0, "Adjustable aluminium trekking poles with cork grips.", ["One Size"], ["Black"]),
    ("Sprint Shorts", "Aerolite", "apparel", 34.0, "Light running shorts with a zip pocket.", ["S", "M", "L", "XL"], ["Black", "Blue"]),
    ("Thermal Base Layer", "Calma", "apparel", 49.0, "Merino-blend long-sleeve base layer for cold-weather runs and hikes.", ["S", "M", "L"], ["Charcoal"]),
]
STORES = [("Downtown San Jose", 37.3349, -121.8881), ("Santana Row", 37.3209, -121.9476), ("Palo Alto", 37.4419, -122.1430), ("Oakland Jack London", 37.7955, -122.2764)]
DELIVERY = [("Store Pickup", 0.0, "today"), ("Standard Home Delivery", 4.99, "3-5 days"), ("Express Delivery", 12.99, "next day")]
USERS = [("alex@example.com", "Alex", 37.3382, -121.8863), ("sam@example.com", "Sam", 37.8044, -122.2712)]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db() -> sqlite3.Connection:
    fresh = not DB.exists()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if fresh:
        con.executescript("""
            CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT UNIQUE, brand TEXT, category TEXT, price REAL, description TEXT, sizes TEXT, colors TEXT);
            CREATE TABLE stores(id INTEGER PRIMARY KEY, name TEXT UNIQUE, lat REAL, lon REAL);
            CREATE TABLE inventory(store_id INTEGER REFERENCES stores(id), product_id INTEGER REFERENCES products(id), qty INTEGER, PRIMARY KEY(store_id, product_id));
            CREATE TABLE delivery_methods(id INTEGER PRIMARY KEY, name TEXT UNIQUE, cost REAL, eta TEXT);
            CREATE TABLE users(email TEXT PRIMARY KEY, first_name TEXT, lat REAL, lon REAL);
            CREATE TABLE cart(user_email TEXT REFERENCES users(email), product_id INTEGER REFERENCES products(id), size TEXT, color TEXT, qty INTEGER DEFAULT 1);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, user_email TEXT REFERENCES users(email), store_id INTEGER REFERENCES stores(id), delivery_method TEXT, items TEXT,
                                total REAL, status TEXT, created_at TEXT);""")
        con.executemany("INSERT INTO products(name, brand, category, price, description, sizes, colors) VALUES(?,?,?,?,?,?,?)", [(*p[:5], json.dumps(p[5]), json.dumps(p[6])) for p in PRODUCTS])
        con.executemany("INSERT INTO stores(name, lat, lon) VALUES(?,?,?)", STORES)
        con.executemany("INSERT INTO delivery_methods(name, cost, eta) VALUES(?,?,?)", DELIVERY)
        con.executemany("INSERT INTO users VALUES(?,?,?,?)", USERS)
        con.executemany("INSERT INTO inventory VALUES(?,?,?)", [(s, p, (s * 7 + p * 3) % 6) for s in range(1, len(STORES) + 1) for p in range(1, len(PRODUCTS) + 1)])
        con.commit()
    return con


def tokens(text: str) -> list[str]:
    return [w.rstrip("s") for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2]


def product_row(r: sqlite3.Row, full: bool = False) -> dict:
    d = {"name": r["name"], "brand": r["brand"], "category": r["category"], "price": r["price"]}
    return d | {"description": r["description"], "sizes": json.loads(r["sizes"]), "colors": json.loads(r["colors"])} if full else d


@mcp.tool()
def search_products(description: str, brand: str = "", max_price: float = 0, limit: int = 5) -> list[dict]:
    """Search the catalogue by a free-text description (e.g. "waterproof shoes for trail running"), optionally filtered by brand and maximum price."""
    with db() as con:
        rows = list(con.execute("SELECT * FROM products"))
    docs = [tokens(f"{r['name']} {r['brand']} {r['category']} {r['description']}") for r in rows]
    df = Counter(w for d in docs for w in set(d))
    q = tokens(description)
    scored = []
    for r, d in zip(rows, docs):
        tf = Counter(d)
        score = sum(tf[w] / len(d) * math.log(1 + len(docs) / df[w]) for w in q if w in tf)
        if (score > 0 or not q) and (not brand or r["brand"].lower() == brand.lower()) and (not max_price or r["price"] <= max_price):
            scored.append((score, product_row(r) | {"relevance": round(score, 3)}))
    scored.sort(key=lambda x: -x[0])
    cutoff = 0.4 * scored[0][0] if scored else 0            # drop weak matches so "trail running shoes" does not return shorts
    return [p for sc, p in scored if sc >= cutoff][:max(1, min(limit, 20))]


@mcp.tool()
def get_product_details(product_name: str) -> dict:
    """Full details of one product: description, available sizes, colours and price."""
    with db() as con:
        r = con.execute("SELECT * FROM products WHERE lower(name) = lower(?)", (product_name,)).fetchone()
    return product_row(r, full=True) if r else {"error": f"no product named '{product_name}'"}


@mcp.tool()
def add_to_cart(user_email: str, product_name: str, size: str, color: str, quantity: int = 1) -> dict:
    """Add a product in a specific size and colour to the signed-in user's cart."""
    with db() as con:
        p = con.execute("SELECT * FROM products WHERE lower(name) = lower(?)", (product_name,)).fetchone()
        if not p:
            return {"error": f"no product named '{product_name}'"}
        if size not in json.loads(p["sizes"]) or color not in json.loads(p["colors"]):
            return {"error": "that size or colour is not available", "sizes": json.loads(p["sizes"]), "colors": json.loads(p["colors"])}
        if not 1 <= quantity <= 10:
            return {"error": "quantity must be between 1 and 10"}
        if not con.execute("SELECT 1 FROM users WHERE email = ?", (user_email,)).fetchone():
            return {"error": "unknown user"}
        con.execute("INSERT INTO cart VALUES(?,?,?,?,?)", (user_email, p["id"], size, color, quantity))
    return {"added": p["name"], "size": size, "color": color, "quantity": quantity}


def _cart(con, email: str) -> tuple[list[dict], float]:
    rows = con.execute("SELECT p.name, p.price, c.size, c.color, c.qty FROM cart c JOIN products p ON p.id = c.product_id WHERE c.user_email = ?", (email,)).fetchall()
    items = [{"name": r["name"], "size": r["size"], "color": r["color"], "quantity": r["qty"], "line_total": round(r["price"] * r["qty"], 2)} for r in rows]
    return items, round(sum(i["line_total"] for i in items), 2)


@mcp.tool()
def show_cart(user_email: str) -> dict:
    """Show the signed-in user's cart with line totals and the subtotal."""
    with db() as con:
        items, subtotal = _cart(con, user_email)
    return {"items": items, "subtotal": subtotal}


@mcp.tool()
def find_nearby_stores(user_email: str, product_name: str = "") -> list[dict]:
    """List stores ordered by distance from the signed-in user; with product_name, also how many units each store has in stock."""
    with db() as con:
        u = con.execute("SELECT * FROM users WHERE email = ?", (user_email,)).fetchone()
        if not u:
            return [{"error": "unknown user"}]
        out = []
        for s in con.execute("SELECT * FROM stores"):
            a = math.radians(s["lat"] - u["lat"]), math.radians(s["lon"] - u["lon"])
            h = math.sin(a[0] / 2) ** 2 + math.cos(math.radians(u["lat"])) * math.cos(math.radians(s["lat"])) * math.sin(a[1] / 2) ** 2
            row = {"store": s["name"], "distance_km": round(6371 * 2 * math.asin(math.sqrt(h)), 1)}
            if product_name:
                q = con.execute("SELECT i.qty FROM inventory i JOIN products p ON p.id = i.product_id WHERE i.store_id = ? AND lower(p.name) = lower(?)", (s["id"], product_name)).fetchone()
                row["in_stock"] = q["qty"] if q else 0
            out.append(row)
    return sorted(out, key=lambda r: r["distance_km"])


@mcp.tool()
def list_delivery_methods() -> list[dict]:
    """Delivery methods with cost and estimated time."""
    with db() as con:
        return [dict(r) for r in con.execute("SELECT name, cost, eta FROM delivery_methods")]


@mcp.tool()
def place_order(user_email: str, store_name: str, delivery_method: str) -> dict:
    """Place an order for everything in the signed-in user's cart, fulfilled by a store, with a delivery method. Empties the cart."""
    with db() as con:
        items, subtotal = _cart(con, user_email)
        s = con.execute("SELECT * FROM stores WHERE lower(name) = lower(?)", (store_name,)).fetchone()
        d = con.execute("SELECT * FROM delivery_methods WHERE lower(name) = lower(?)", (delivery_method,)).fetchone()
        if not items:
            return {"error": "the cart is empty"}
        if not s or not d:
            return {"error": "unknown store or delivery method"}
        total = round(subtotal + d["cost"], 2)
        cur = con.execute("INSERT INTO orders(user_email, store_id, delivery_method, items, total, status, created_at) VALUES(?,?,?,?,?,?,?)",
                          (user_email, s["id"], d["name"], json.dumps(items), total, "confirmed", now()))
        con.execute("DELETE FROM cart WHERE user_email = ?", (user_email,))
    return {"order_id": cur.lastrowid, "total": total, "status": "confirmed", "delivery": d["name"], "eta": d["eta"]}


@mcp.tool()
def list_orders(user_email: str) -> list[dict]:
    """The signed-in user's orders: id, total, status, delivery method."""
    with db() as con:
        return [dict(r) for r in con.execute("SELECT id AS order_id, total, status, delivery_method, created_at FROM orders WHERE user_email = ? ORDER BY id DESC", (user_email,))]


@mcp.tool()
def cancel_order(user_email: str, order_id: int) -> dict:
    """Cancel one of the signed-in user's orders if it has not shipped."""
    with db() as con:
        o = con.execute("SELECT * FROM orders WHERE id = ? AND user_email = ?", (order_id, user_email)).fetchone()   # ownership check in SQL
        if not o:
            return {"error": f"order {order_id} not found for this user"}
        if o["status"] != "confirmed":
            return {"error": f"order is {o['status']} and cannot be cancelled"}
        con.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    return {"order_id": order_id, "status": "cancelled"}


if __name__ == "__main__":
    mcp.run()
