# Build a static HTML snapshot of my training activities.
# Works with .env locally and in GitHub Actions (with repo secrets)

import os
import sys
import pathlib
import pytz
from datetime import datetime, timezone
from html import escape
from typing import Any, Iterable, List
from time import strftime
from jinja2 import Template
from todoist_api_python.api import TodoistAPI

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

TOKEN = (os.getenv("TODOIST_TOKEN") or "").strip()
PROJECT_ID = (os.getenv("TODOIST_PROJECT_ID") or "").strip()
PROJECT_NAME = (os.getenv("TODOIST_PROJECT_NAME") or "").strip()
PRIORITY_EXCLUDE = (os.getenv("EXCLUDE_PRIORITIES") or "").strip()


if not TOKEN:
    print("ERROR: Missing TODOIST_TOKEN environment variable.", file=sys.stderr)
    sys.exit(1)

api = TodoistAPI(TOKEN)

def _as_list(maybe_iterable: Iterable[Any]) -> List[Any]:
    """
    Normalize ResultsPaginator / generator / list / nested-lists into a flat list.
    """
    flat: List[Any] = []

    for item in maybe_iterable:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    return flat

def _get(obj: Any, attr: str, default: Any = None) -> Any:
    """
    Get attribute or dict key safely.
    """
    if hasattr(obj, attr):
        try:
            return getattr(obj, attr)
        except Exception:
            pass
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return default

def _format_due(due_obj: Any) -> str:
    """
    Todoist due can be None, an SDK Due object, or a dict.
    Prefer 'string', then 'datetime', then 'date'.
    """
    if not due_obj:
        return ""
    # SDK object
    s = getattr(due_obj, "string", None) or getattr(due_obj, "datetime", None) or getattr(due_obj, "date", None)
    if s:
        return str(s)
    # dict
    if isinstance(due_obj, dict):
        return str(due_obj.get("string") or due_obj.get("datetime") or due_obj.get("date") or "")
    return ""

def find_project_id() -> str:
    """
    Resolve project by ID or by exact name (case-insensitive).
    Supports SDK objects, dicts, and paginator returns.
    """
    if PROJECT_ID:
        return PROJECT_ID
    if not PROJECT_NAME:
        print("ERROR: Provide TODOIST_PROJECT_ID or TODOIST_PROJECT_NAME.", file=sys.stderr)
        sys.exit(1)

    projects_iter = api.get_projects()
    projects = _as_list(projects_iter)

    for p in projects:
        name = _get(p, "name", None)
        if name and str(name).lower() == PROJECT_NAME.lower():
            pid = _get(p, "id", None)
            if pid:
                return str(pid)

    sample_type = type(projects[0]).__name__ if projects else "EMPTY"
    print(
        f'ERROR: Project named "{PROJECT_NAME}" not found. '
        f"Fetched {len(projects)} projects; first item type: {sample_type}",
        file=sys.stderr,
    )
    sys.exit(1)

TEMPLATE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Tasks — {{ project_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root { font-family: 'JetBrains Mono', system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  body { margin: 0; background: #fff; color: #111; }
  .container { margin: 2rem auto; padding: 0 1rem; max-width: 1400px; }

  header { margin-bottom: 1rem; }
  h1 { margin: 0 0 .25rem 0; font-size: 1.8rem; }
  .updated { color: #666; font-size: .9rem; }

  /* 4-column responsive board */
  .board {
    display: grid;
    gap: 1rem;
    grid-template-columns: 1fr; /* phones */
  }
  @media (min-width: 800px) {
    .board { grid-template-columns: repeat(2, 1fr); } /* tablets */
  }
  @media (min-width: 1200px) {
    .board { grid-template-columns: repeat(5, 1fr); } /* desktops */
  }

  .column {
    background: #fafafa;
    border: 1px solid #eee;
    border-radius: 12px;
    padding: .75rem;
    min-height: 3rem;
  }
  .column h2 {
    margin: .25rem .25rem .75rem;
    font-size: 1.05rem;
    font-weight: 700;
  }

  ul.tasks {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: 1fr;
    gap: .75rem;
  }

  .task {
    border: 1px solid #e5e5e5;
    border-radius: 12px;
    padding: .8rem 1rem;
    box-sizing: border-box;
    background: #fff;
  }

  .top { display: flex; gap: .5rem; align-items: baseline; justify-content: space-between; }
  .content { font-weight: 600; }
  .meta { color: #555; font-size: .92rem; display: flex; gap: .8rem; margin-top: .4rem; flex-wrap: wrap; }

  .p4 { border-left: 6px solid #3b82f6; padding-left: .75rem; }
  .p3 { border-left: 6px solid #22c55e; padding-left: .75rem; }
  .p2 { border-left: 6px solid #f59e0b; padding-left: .75rem; }
  .p1 { border-left: 6px solid #ef4444; padding-left: .75rem; }

  footer { margin-top: 2rem; color: #666; font-size: .85rem; }
</style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{{ project_name }}</h1>
      <div class="updated">Last updated: {{ updated_iso }}</div>
    </header>

    <main>
      {% if columns %}
        <div class="board">
          {% for col in columns %}
            <section class="column">
              <h2>{{ col }}</h2>
              {% set items = tasks_by_section.get(col, []) %}
              {% if items %}
                <ul class="tasks">
                  {% for t in items %}
                    <li class="task {{ t.priority_class }}">
                      <div class="top">
                        <span class="content">{{ t.content }}</span>
                      </div>
                      <div class="meta">
                        {% if t.due %}<span class="due">🗓 {{ t.due }}</span>{% endif %}
                        {% if t.labels %}<span class="labels">🏷 {{ t.labels|join(', ') }}</span>{% endif %}
                        {% if t.section and t.section != col %}<span class="section">📁 {{ t.section }}</span>{% endif %}
                      </div>
                    </li>
                  {% endfor %}
                </ul>
              {% else %}
                <p style="color:#777; margin:.25rem .5rem;">No tasks</p>
              {% endif %}
            </section>
          {% endfor %}
        </div>
      {% else %}
        <p>No open tasks in this project 🎉</p>
      {% endif %}
    </main>

    <footer>
      <p>For specific details on a Training Activity consult <a href="https://curriculumlibrary.nshcs.org.uk/stp/specialty/SBI1-2-23/">This Page.</a></p>
    </footer>
  </div>
</body>
</html>
""")

def build():
    exclude_raw = (os.getenv("EXCLUDE_PRIORITIES") or "").strip()
    exclude_set = set()
    if exclude_raw:
        for part in exclude_raw.split(","):
            part = part.strip()
            if part.isdigit():
                n = int(part)
                if 1 <= n <= 4:
                    exclude_set.add(n)
    project_id = find_project_id()

    # Get project (for its name)
    project = api.get_project(project_id)
    project_name = escape(_get(project, "name", "Todoist Project") or "Todoist Project")

    # Open (incomplete) tasks in this project
    tasks_iter = api.get_tasks(project_id=project_id)
    tasks = _as_list(tasks_iter)

    # Optional: sections map
    section_name_by_id = {}
    try:
        sections_iter = api.get_sections(project_id=project_id)
        sections = _as_list(sections_iter)
        section_name_by_id = { str(_get(s, "id")): _get(s, "name", "") for s in sections }
    except Exception:
        pass

    # Sort tasks by 'order' then 'id'
    def sort_key(t: Any):
        order = _get(t, "order", 0) or 0
        try:
            order = int(order)
        except Exception:
            order = 0
        tid = str(_get(t, "id", "")) or ""
        return (order, tid)

    tasks.sort(key=sort_key)

    # Build view models
    view_models = []
    for t in tasks:
        prio = _get(t, "priority", 3)
        try:
            prio = int(prio)
        except Exception:
            prio = 3

        # 🚫 Skip excluded priorities
        if prio in exclude_set:
            continue
        content = escape(_get(t, "content", "") or "")
        due_str = escape(_format_due(_get(t, "due")))
        labels = _get(t, "labels", []) or []
        labels = [escape(str(x)) for x in labels]
        section_id = _get(t, "section_id")
        section_name = ""
        if section_id is not None:
            section_name = section_name_by_id.get(str(section_id), "") or ""
        prio = _get(t, "priority", 3)
        try:
            prio = int(prio)
        except Exception:
            prio = 3
        url = _get(t, "url", "") or ""

        view_models.append({
            "content": content,
            "due": due_str,
            "labels": labels,
            "priority_class": f"p{prio}",
            "url": url,
            "section": escape(section_name) or "Unassigned",
        })

    # -------- Choose the 4 columns (section titles) --------
    # From .env -> SECTIONS=Col1|Col2|Col3|Col4
    configured = (os.getenv("SECTIONS") or "").strip()
    if configured:
        col_titles = [s.strip() for s in configured.split("|") if s.strip()]
    else:
        # default: first 4 discovered sections; ensure stable order
        discovered = []
        for t in view_models:
            sec = t["section"]
            if sec and sec not in discovered:
                discovered.append(sec)
        col_titles = discovered[:5]
    # Pad to 4 columns and add an "Other" sink
    while len(col_titles) < 5:
        col_titles.append(f"Column {len(col_titles)+1}")
    other_col = "Other"

    # -------- Bucket tasks into those 4 columns + "Other" --------
    buckets = {title: [] for title in col_titles}
    buckets[other_col] = []
    title_set = set(col_titles)

    for t in view_models:
        sec = t["section"] or "Unassigned"
        if sec in title_set:
            buckets[sec].append(t)
        else:
            buckets[other_col].append(t)

    # Optional: sort within each bucket (by priority then due text)
    def vm_sort_key(t):
        # priority_class like "p1".."p4" -> lower is higher priority
        try:
            pr = int(t["priority_class"][1:])
        except Exception:
            pr = 3
        return (pr, t["due"], t["content"])

    for k in buckets:
        buckets[k].sort(key=vm_sort_key)

    # If "Other" is empty, drop it; else place it at the end
    if not buckets[other_col]:
        buckets.pop(other_col, None)
        ordered_titles = col_titles
    else:
        ordered_titles = col_titles + [other_col]

    london_tz = pytz.timezone("Europe/London")

    html = TEMPLATE.render(
        project_name=project_name,
        
        updated_iso = datetime.now(london_tz).strftime("%Y-%m-%d %H:%M:%S"),
        columns=ordered_titles,
        tasks_by_section=buckets,
    )

    out_dir = pathlib.Path("dist")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"Wrote dist/index.html with {len(view_models)} open tasks.")

def main():
    try:
        build()
    except Exception as e:
        # Keep logs
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
