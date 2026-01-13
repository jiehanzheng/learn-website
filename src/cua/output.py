from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PdpRecord:
    index: int
    url: Optional[str]
    steps: List[Dict[str, Any]] = field(default_factory=list)


class PdpWriter:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._current: Optional[PdpRecord] = None

    def start(self, index: int, url: Optional[str]) -> None:
        self._current = PdpRecord(index=index, url=url)

    def add_step(self, step: Dict[str, Any]) -> None:
        if not self._current:
            return
        self._current.steps.append(step)

    def finish(self) -> Optional[Path]:
        if not self._current:
            return None
        path = self.out_dir / f"pdp_{self._current.index:03d}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "index": self._current.index,
                    "url": self._current.url,
                    "steps": self._current.steps,
                },
                f,
                indent=2,
                ensure_ascii=True,
            )
        self._current = None
        return path
