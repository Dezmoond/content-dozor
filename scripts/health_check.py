# -*- coding: utf-8 -*-
"""Health check helper for start_platform.ps1"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def check_url(url: str, timeout: float = 3.0) -> dict:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body[:200]}
            return {"ok": True, "status": resp.status, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: health_check.py <url>"}))
        return 1
    result = check_url(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
