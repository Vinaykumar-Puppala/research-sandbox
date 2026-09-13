# Skills folder

Drop files here to extend the **Chat With My Data** agent with your own analytics tools and instructions. Changes take effect on the next chat request — no restart needed.

---

## Python tool skills (`.py` files)

Define one or more `@tool`-decorated functions. The agent can call them just like the built-in tools (`inspect_schema`, `readonly_sql`, etc.).

```python
# research_sandbox/skills/my_cohort_tool.py
from langchain_core.tools import tool

@tool
def cohort_retention(table: str, cohort_column: str, event_column: str) -> str:
    """Calculate week-over-week retention for cohorts in a SQLite table.

    Args:
        table: Name of the data table.
        cohort_column: Column identifying the cohort (e.g. signup_week).
        event_column: Column identifying the activity event.
    """
    import sqlite3, os, json
    db = os.getenv("DISCOVERY_DB", "discovery_final.db")
    with sqlite3.connect(db) as conn:
        ...
    return json.dumps(result)
```

**Rules:**
- Must use `from langchain_core.tools import tool` and the `@tool` decorator.
- The docstring is what the model reads to decide when to call the tool — make it clear.
- Only read from the database; never write.
- Use `os.getenv("DISCOVERY_DB")` to get the database path.

---

## Instruction skills (`.md` files)

Plain markdown injected into the agent's system prompt before every chat request.

```markdown
# my_instructions.md

When the user asks about revenue, always:
1. Break it down by product_line first.
2. Show month-over-month change.
3. Flag any month where revenue dropped more than 10 %.
```

---

## Conventions

| Convention | Meaning |
|---|---|
| `my_tool.py` | Active — loaded automatically |
| `_draft_tool.py` | Skipped — underscore prefix marks drafts/examples |
| `README.md` | Skipped — never injected as a skill |

See `_example_tool.py` and `_example_prompt.md` for copy-paste starting points.
