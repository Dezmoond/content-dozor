# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PipelineContext:
    case_id: Optional[str] = None
    document_id: Optional[str] = None
    user_id: Optional[str] = None
    text: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    steps_log: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def log_step(self, step_id: str, status: str, detail: Any = None, duration_ms: float = 0) -> None:
        self.steps_log.append(
            {
                "step_id": step_id,
                "status": status,
                "detail": detail,
                "duration_ms": duration_ms,
            }
        )
