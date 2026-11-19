"""Scripted model turns for the offline demo/test (not an LLM). The MCP server, SQLite data, identity injection,
confirmation gate and audit trail are real. Turn 5 has the "model" try to use another customer's email on purpose."""
from common.scripted_llm import call

TURNS = ["I need waterproof shoes for trail running, under $150.", "Add the Trailblazer GTX in size 42, Black/Lime.", "Which store near me has it, and what are the delivery options?",
         "Order it from the nearest store with express delivery.", "Yes, confirm the order.", "Show my orders."]
SCRIPT = {"shop_assistant": [
    call("search_products", description="waterproof shoes for trail running", max_price=150),
    lambda c: "I found: " + "; ".join(f"{p['name']} ({p['brand']}) ${p['price']:.2f}" for p in c.last_tool),
    call("get_product_details", product_name="Trailblazer GTX"), call("add_to_cart", user_email="someone-else@example.com", product_name="Trailblazer GTX", size="42", color="Black/Lime"),
    lambda c: f"Added {c.last_tool['added']} (size {c.last_tool['size']}, {c.last_tool['color']}) to your cart.",
    [call("find_nearby_stores", user_email="x", product_name="Trailblazer GTX"), call("list_delivery_methods")],
    lambda c: "Nearest stores: " + "; ".join(f"{s['store']} {s['distance_km']} km ({s['in_stock']} in stock)" for s in c.results("find_nearby_stores")[-1][:3])
              + ". Delivery: " + "; ".join(f"{d['name']} ${d['cost']:.2f} ({d['eta']})" for d in c.results("list_delivery_methods")[-1]),
    call("place_order", user_email="x", store_name="Downtown San Jose", delivery_method="Express Delivery"),
    lambda c: "Before I place it: Trailblazer GTX, size 42, from Downtown San Jose with Express Delivery ($12.99) — total $151.99. Shall I confirm?",
    call("place_order", user_email="x", store_name="Downtown San Jose", delivery_method="Express Delivery"),
    lambda c: f"Order #{c.last_tool['order_id']} is {c.last_tool['status']}: total ${c.last_tool['total']:.2f}, {c.last_tool['delivery']} ({c.last_tool['eta']}).",
    call("list_orders", user_email="x"), lambda c: "Your orders: " + "; ".join(f"#{o['order_id']} ${o['total']:.2f} {o['status']}" for o in c.last_tool),
]}
