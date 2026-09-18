# -*- coding: utf-8 -*-
"""Extract key functions from notebook into platform_plugins (reference)."""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[2] / "1_ПЕРВЫЙ_НОУТБУК_ФИНАЛЬНЫЙ.ipynb"
OUT = Path(__file__).resolve().parents[1] / "packages" / "platform_plugins" / "processors" / "_notebook_extracted.py"

FUNCTIONS = [
    "split_text_chunks",
    "read_docx_text",
    "enrich_hits",
    "orchestrate_entities",
    "analyze_text",
]


def main():
    if not NOTEBOOK.is_file():
        print(f"Notebook not found: {NOTEBOOK}")
        return
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    found = []
    for cell in nb.get("cells", []):
        src = "".join(cell.get("source", []))
        for fn in FUNCTIONS:
            if f"def {fn}" in src:
                found.append(f"# --- {fn} ---\n{src}\n")
    OUT.write_text(
        "# Auto-extracted from notebook. Prefer plugin modules for production.\n\n" + "\n".join(found),
        encoding="utf-8",
    )
    print(f"Wrote {OUT} ({len(found)} cells)")


if __name__ == "__main__":
    main()
