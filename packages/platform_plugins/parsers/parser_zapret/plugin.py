# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from platform_core.config import get_settings
from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class

PARSER_IDS = [
    "rosfinmonitoring",
    "minjust_undesirable",
    "minjust_extremist_orgs",
    "fsb_terror_orgs",
    "minjust_foreign_agents",
    "minjust_foreign_agents_orgs",
    "minjust_extremist_materials",
    "rknweb_blocked_sites",
]

# обратная совместимость со старыми id
LEGACY_TO_NEW = {
    "parser1": "rosfinmonitoring",
    "parser2": "minjust_undesirable",
    "parser3": "minjust_extremist_orgs",
    "parser4": "fsb_terror_orgs",
    "parser5": "minjust_foreign_agents",
    "parser6": "minjust_foreign_agents_orgs",
    "parser7": "minjust_extremist_materials",
    "rknweb_blocked_sites": "rknweb_blocked_sites",
}

PARSER_TITLES = {
    "rosfinmonitoring": "Каталог террористов и экстремистов Росфинмониторинга",
    "minjust_undesirable": "Перечень нежелательных организаций Минюста",
    "minjust_extremist_orgs": "Перечень экстремистских организаций Минюста",
    "fsb_terror_orgs": "Единый список террористических организаций ФСБ",
    "minjust_foreign_agents": "Реестр иноагентов Минюста",
    "minjust_foreign_agents_orgs": "Реестр иноагентов Минюста и организаций",
    "minjust_extremist_materials": "Перечень экстремистских материалов Минюста",
    "rknweb_blocked_sites": "Реестр заблокированных сайтов",
}

# id платформы → id subprocess PARSER_ONLY (parser_zapret)
NEW_TO_ZAPRET = {
    "rosfinmonitoring": "parser1",
    "minjust_undesirable": "parser2",
    "minjust_extremist_orgs": "parser3",
    "fsb_terror_orgs": "parser4",
    "minjust_foreign_agents": "parser5",
    "minjust_foreign_agents_orgs": "parser6",
    "minjust_extremist_materials": "parser7",
    "rknweb_blocked_sites": "rknweb_blocked_sites",
}


def _ensure_app_blacklist(diplom: Path) -> Path:
    """Сид CSV в analysis_platform/data/blacklist при первом запуске."""
    local = diplom / "local_parsers"
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))
    from registry_update import default_app_blacklist_dir, ensure_app_blacklist_seeded

    app_bl = default_app_blacklist_dir(diplom)
    ensure_app_blacklist_seeded(app_bl)
    return app_bl


@register_plugin_class
class ParserZapretPlugin(Plugin):
    meta = PluginMeta(
        id="parser_zapret",
        name="Parser Zapret",
        kind=PluginKind.PARSER,
        description="Парсеры госреестров (parser_zapret)",
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Dict[str, Any]:
        settings = get_settings()
        raw_id = ctx.config.get("parser_id", "minjust_extremist_materials")
        parser_id = LEGACY_TO_NEW.get(raw_id, raw_id)
        zapret_id = NEW_TO_ZAPRET.get(parser_id, parser_id)
        diplom = Path(settings.diplom_root)
        local_root = diplom / "local_parsers"
        parser_root = diplom / "parser_zapret"

        app_bl = _ensure_app_blacklist(diplom)
        # staging по датам; после успеха — apply в app blacklist
        default_runs = Path(settings.resolved_parser_runs_dir())
        output_root = Path(ctx.config.get("output_dir") or str(default_runs))
        output_root.mkdir(parents=True, exist_ok=True)
        apply_app = bool(ctx.config.get("apply_to_app", True))

        if local_root.is_dir() and (local_root / "run_gui.py").is_file():
            cmd = [
                sys.executable,
                str(local_root / "run_gui.py"),
                "--cli",
                parser_id,
                "--output",
                str(output_root),
            ]
            if apply_app:
                cmd.append("--apply-app")
            env = {**dict(**{k: str(v) for k, v in __import__("os").environ.items()})}
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(local_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=int(ctx.config.get("timeout", 3600)),
                )
                return {
                    "status": "ok" if proc.returncode == 0 else "error",
                    "parser_id": parser_id,
                    "title": PARSER_TITLES.get(parser_id, parser_id),
                    "backend": "local_parsers",
                    "output_dir": str(output_root),
                    "app_blacklist": str(app_bl),
                    "apply_to_app": apply_app,
                    "stdout": proc.stdout[-4000:] if proc.stdout else "",
                    "stderr": proc.stderr[-2000:] if proc.stderr else "",
                    "returncode": proc.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"status": "timeout", "parser_id": parser_id}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        if not parser_root.is_dir():
            return {"status": "error", "message": f"parsers not found: {local_root} / {parser_root}"}

        # fallback: parser_zapret → дата-папка, затем apply через registry_update
        from datetime import date

        run_dir = output_root / date.today().strftime("%Y-%m-%d")
        run_dir.mkdir(parents=True, exist_ok=True)
        env = {
            **dict(**{k: str(v) for k, v in __import__("os").environ.items()}),
            "PARSER_ONLY": zapret_id,
            "PARSER_OUTPUT_DIR": str(run_dir),
        }
        try:
            proc = subprocess.run(
                [sys.executable, str(parser_root / "main.py")],
                cwd=str(parser_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=int(ctx.config.get("timeout", 3600)),
            )
            apply_report = None
            if apply_app and proc.returncode == 0:
                if str(local_root) not in sys.path:
                    sys.path.insert(0, str(local_root))
                from registry_update import apply_run_to_app_blacklist

                apply_report = apply_run_to_app_blacklist(run_dir, app_bl)
            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "parser_id": parser_id,
                "title": PARSER_TITLES.get(parser_id, parser_id),
                "backend": "parser_zapret",
                "output_dir": str(run_dir),
                "app_blacklist": str(app_bl),
                "apply_to_app": apply_app,
                "apply_report": apply_report,
                "stdout": proc.stdout[-4000:] if proc.stdout else "",
                "stderr": proc.stderr[-2000:] if proc.stderr else "",
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "parser_id": parser_id}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


def list_parsers() -> List[str]:
    return list(PARSER_IDS)


def list_parsers_detailed() -> List[Dict[str, str]]:
    return [{"id": pid, "name": PARSER_TITLES.get(pid, pid)} for pid in PARSER_IDS]
