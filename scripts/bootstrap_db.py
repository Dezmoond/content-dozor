# -*- coding: utf-8 -*-
"""DB init for startup (minimal, sync-friendly)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(ROOT / 'data' / 'platform.db').as_posix()}")
os.environ.setdefault("DIPLOM_ROOT", str(ROOT.parent))


async def main() -> None:
    from platform_core.db.session import init_db
    await init_db()


def maybe_seed() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "packages"), str(ROOT)])
    for script in ("seed_settings.py", "seed_users.py"):
        seed_py = ROOT / "scripts" / script
        if not seed_py.is_file():
            continue
        subprocess.run(
            [sys.executable, str(seed_py)],
            cwd=str(ROOT),
            env=env,
            check=False,
        )


if __name__ == "__main__":
    asyncio.run(main())
    maybe_seed()
    print("Инициализация завершена.")
