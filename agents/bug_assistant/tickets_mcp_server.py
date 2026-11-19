"""A real MCP server (stdio transport) exposing a bug-ticket database as tools.

    python agents/bug_assistant/tickets_mcp_server.py            # speaks MCP on stdin/stdout
The ADK agent connects to it through McpToolset. The database is SQLite (TICKETS_DB, default ./tickets.db), seeded on
first start with a few synthetic tickets. Every query is parameterised; status and priority are validated.
"""
from __future__ import annotations
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:                                    # mcp 2.x renamed FastMCP to MCPServer; support both
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

DB = Path(os.environ.get("TICKETS_DB", Path(__file__).parent / "tickets.db"))
STATUSES = ("open", "in_progress", "resolved", "closed")
PRIORITIES = ("P0", "P1", "P2", "P3")
SEED = [
    ("Login fails with 500 after password reset", "After resetting the password, the first login returns HTTP 500. Stack trace points to SessionStore.rotate(): KeyError 'csrf'.", "open", "P1", "auth"),
    ("Checkout total ignores discount code on mobile", "Discount applies on desktop but the mobile web checkout shows the undiscounted total. Started after release 4.12.", "open", "P1", "checkout"),
    ("CSV export times out for large accounts", "Exporting more than 50k rows returns 504 after 60 seconds. Export runs synchronously in the request thread.", "in_progress", "P2", "reports"),
    ("Dark mode: chart labels unreadable", "Axis labels render dark grey on a black background in dark mode.", "open", "P3", "ui"),
    ("Session expires during file upload", "Uploads longer than 15 minutes fail with 401 because the session token is not refreshed mid-upload.", "open", "P2", "auth"),
    ("Password reset email sent twice", "Users receive two reset emails. Retry logic fires even when the first send succeeded.", "resolved", "P3", "auth"),
    ("Search returns stale results after product rename", "Index is refreshed nightly only; renamed products keep the old name in search for up to 24 hours.", "open", "P2", "search"),
]
mcp = FastMCP("tickets")


def db() -> sqlite3.Connection:
    fresh = not DB.exists()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if fresh:
        con.executescript("""CREATE TABLE tickets(id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL, priority TEXT NOT NULL,
                               component TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                             CREATE TABLE comments(id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id), body TEXT NOT NULL, created_at TEXT NOT NULL);""")
        con.executemany("INSERT INTO tickets(title, description, status, priority, component, created_at, updated_at) VALUES(?,?,?,?,?,?,?)", [(*s, now(), now()) for s in SEED])
        con.commit()
    return con


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in {"the", "and", "with", "for", "after", "not", "are", "returns", "when", "from"}}


@mcp.tool()
def search_tickets(query: str = "", status: str = "", component: str = "", limit: int = 10) -> list[dict]:
    """Search tickets by keywords in title/description, optionally filtered by status (open, in_progress, resolved, closed) and component."""
    sql, args = "SELECT id, title, status, priority, component FROM tickets WHERE 1=1", []
    for w in list(words(query))[:8]:
        sql += " AND (lower(title) LIKE ? OR lower(description) LIKE ?)"; args += [f"%{w}%"] * 2
    if status:
        sql += " AND status = ?"; args.append(status)
    if component:
        sql += " AND component = ?"; args.append(component)
    with db() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY priority, id LIMIT ?", (*args, max(1, min(limit, 50))))]


@mcp.tool()
def get_ticket(ticket_id: int) -> dict:
    """Get one ticket with its full description and comments."""
    with db() as con:
        t = con.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not t:
            return {"error": f"ticket {ticket_id} not found"}
        return dict(t) | {"comments": [dict(c) for c in con.execute("SELECT body, created_at FROM comments WHERE ticket_id = ? ORDER BY id", (ticket_id,))]}


@mcp.tool()
def find_similar_tickets(text: str, limit: int = 3) -> list[dict]:
    """Find existing tickets that look like a new bug report (word-overlap similarity). Use before creating a ticket to avoid duplicates."""
    q = words(text)
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT id, title, description, status, priority FROM tickets")]
    scored = []
    for r in rows:
        t = words(r["title"] + " " + r["description"])
        sim = len(q & t) / max(1, len(q | t))
        if sim >= 0.08:
            scored.append({"id": r["id"], "title": r["title"], "status": r["status"], "priority": r["priority"], "similarity": round(sim, 2)})
    return sorted(scored, key=lambda x: -x["similarity"])[:limit]


@mcp.tool()
def create_ticket(title: str, description: str, priority: str = "P2", component: str = "general") -> dict:
    """Create a new bug ticket. Priority is P0 (outage) to P3 (cosmetic)."""
    if priority not in PRIORITIES:
        return {"error": f"priority must be one of {PRIORITIES}"}
    if not (5 <= len(title) <= 200) or len(description) < 10:
        return {"error": "title must be 5-200 characters and description at least 10"}
    with db() as con:
        cur = con.execute("INSERT INTO tickets(title, description, status, priority, component, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                          (title, description, "open", priority, component, now(), now()))
        return {"id": cur.lastrowid, "status": "open", "priority": priority}


@mcp.tool()
def update_ticket_status(ticket_id: int, status: str) -> dict:
    """Change a ticket's status to open, in_progress, resolved or closed."""
    if status not in STATUSES:
        return {"error": f"status must be one of {STATUSES}"}
    with db() as con:
        n = con.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?", (status, now(), ticket_id)).rowcount
    return {"id": ticket_id, "status": status} if n else {"error": f"ticket {ticket_id} not found"}


@mcp.tool()
def add_comment(ticket_id: int, body: str) -> dict:
    """Add a comment (triage notes, reproduction steps, suspected cause) to a ticket."""
    with db() as con:
        if not con.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone():
            return {"error": f"ticket {ticket_id} not found"}
        con.execute("INSERT INTO comments(ticket_id, body, created_at) VALUES(?,?,?)", (ticket_id, body, now()))
    return {"ticket_id": ticket_id, "added": True}


if __name__ == "__main__":
    mcp.run()
