"""Scripted model turns for the offline demo/test (not an LLM). The MCP server, its SQLite database and the guard are real."""
from common.scripted_llm import call

NEW = "PDF invoices render blank in Safari 18; Chrome and Firefox are fine. Started this week."
DUP = "Login returns 500 right after I reset my password"


def after_similar(c):
    hits = c.last_tool or []
    top = hits[0] if hits else None
    if top and top["similarity"] >= 0.25:
        return call("add_comment", ticket_id=top["id"], body=f"Another report: {c.user}")
    return call("create_ticket", title="PDF invoices render blank in Safari 18", description=f"Steps: open any invoice PDF in Safari 18. Expected: invoice renders. Actual: blank page. Reporter notes: {c.user}", priority="P2", component="billing")


def wrap_up(c):
    r = c.last_tool
    if "added" in str(r):
        return f"This looks like existing ticket #{r['ticket_id']} — I added your report as a comment instead of opening a duplicate."
    return f"Created ticket #{r['id']} (P2: invoices are degraded in one browser, there is a workaround)."


SCRIPT = {"bug_assistant": [
    lambda c: call("find_similar_tickets", text=c.user), after_similar, wrap_up,                                  # turn 1: new bug
    lambda c: call("find_similar_tickets", text=c.user), after_similar, wrap_up,                                  # turn 2: duplicate
    call("search_tickets", status="open", component="auth"), lambda c: "Open auth bugs: " + "; ".join(f"#{t['id']} {t['title']} ({t['priority']})" for t in c.last_tool),   # turn 3
    call("update_ticket_status", ticket_id=2, status="closed"), lambda c: f"I could not close it: {c.last_tool.get('error', c.last_tool)}",                                 # turn 4: guard refuses
    call("update_ticket_status", ticket_id=4, status="resolved"), lambda c: f"Ticket #{c.last_tool['id']} is now {c.last_tool['status']}.",                                  # turn 5: allowed
]}
TURNS = [NEW, DUP, "What auth bugs are open?", "Clean up the old tickets for me.", "Mark ticket 4 as resolved."]
