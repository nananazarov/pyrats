# 🏴‍☠️ PYRATS — Python Rule Automation Table System

A dead-simple, lightweight Python clone of **GoRules** (https://gorules.io/) decision tables. 

No nested AND/OR tree UI pain. Just a flat split table (CONDITIONS | RESULTS), standard cell expression syntax, and automatic evaluation endpoints.

---

## 🎯 Supported Cell Syntax

Standard GoRules-style expressions:
- **Comparisons**: `> 100`, `< 50`, `>= 18`, `<= 65`, `== "active"`, `!= 0`
- **Ranges**: `[1..100]` (inclusive), `(0..100)` (exclusive), `[18..65)` (mixed)
- **Lists (OR)**: `'US', 'CA', 'GB'` (strings), `1, 2, 3` (numbers)
- **AND/OR Combos**: `> 0 and < 100`, `< 0 or > 100`
- **Wildcard**: `*` or empty cell matches anything

*Multiple inputs on the same row are combined via AND logic.*

---

## ⚡ Tech Stack

Simple, no-build vanilla stack:
- **Backend**: FastAPI (endpoints/router), SQLite (rules persistence in `rules.db`), Pydantic (data parsing)
- **Frontend**: Bootstrap 5 (grid & buttons), HTMX (handles blur-to-save cell edits, column/row additions), Alpine.js (reactive tab switching & JSON tester sandbox)

---

## 🚀 How to Run

Just use `uv` and go:

```bash
# Install deps and spin up uvicorn reload server
uv run uvicorn app:app --reload

# Open the dashboard
# http://127.0.0.1:8000
```

---

## 🦾 Credits

Crafted in pair programming.  
**Antigravity** — Google DeepMind's agentic AI pair programming partner.
