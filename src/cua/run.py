from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import html
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StepRecord:
    index: int
    url: str
    viewport: Dict[str, Any]
    screenshot: str
    request: Optional[str] = None
    response: Optional[str] = None
    actions: Optional[str] = None
    ts: float = 0.0
    notes: Optional[str] = None


@dataclass
class RunLogger:
    root: Path
    steps_dir: Path
    pdps_dir: Path
    step_records: List[StepRecord] = field(default_factory=list)
    step_index: int = 0

    def next_step(self, *, url: str, viewport: Dict[str, Any], screenshot_bytes: bytes, ts: float) -> StepRecord:
        self.step_index += 1
        step_id = f"{self.step_index:04d}"
        screenshot_path = self.steps_dir / f"step_{step_id}.png"
        screenshot_path.write_bytes(screenshot_bytes)

        record = StepRecord(
            index=self.step_index,
            url=url,
            viewport=viewport,
            screenshot=str(Path("steps") / screenshot_path.name),
            ts=ts,
        )
        self.step_records.append(record)
        self._write_index()
        return record

    def write_request(self, record: StepRecord, payload: Dict[str, Any]) -> None:
        path = self.steps_dir / f"step_{record.index:04d}_request.json"
        _write_json(path, payload)
        record.request = str(Path("steps") / path.name)
        self._write_index()

    def write_response(self, record: StepRecord, payload: Dict[str, Any]) -> None:
        path = self.steps_dir / f"step_{record.index:04d}_response.json"
        _write_json(path, payload)
        record.response = str(Path("steps") / path.name)
        self._write_index()

    def write_actions(self, record: StepRecord, payload: Dict[str, Any]) -> None:
        path = self.steps_dir / f"step_{record.index:04d}_actions.json"
        _write_json(path, payload)
        record.actions = str(Path("steps") / path.name)
        self._write_index()

    def write_run_info(self, info: Dict[str, Any]) -> None:
        path = self.root / "run.json"
        _write_json(path, info)

    def write_report(self) -> Path:
        report_path = self.root / "report.html"
        html = _build_report_html(self.step_records, self.root)
        report_path.write_text(html, encoding="utf-8")
        return report_path

    def _write_index(self) -> None:
        path = self.steps_dir / "index.json"
        _write_json(path, {
            "steps": [record.__dict__ for record in self.step_records],
        })


def create_run_logger(base_dir: Path, host: str, run_name: Optional[str]) -> RunLogger:
    host_dir = base_dir / host
    host_dir.mkdir(parents=True, exist_ok=True)

    if run_name:
        stem = run_name
    else:
        stem = datetime.now().strftime("run_%Y%m%d_%H%M%S")

    root = _unique_path(host_dir / stem)
    root.mkdir(parents=True)

    steps_dir = root / "steps"
    pdps_dir = root / "pdps"
    steps_dir.mkdir(parents=True)
    pdps_dir.mkdir(parents=True)

    return RunLogger(root=root, steps_dir=steps_dir, pdps_dir=pdps_dir)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = Path(f"{path}_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _build_report_html(records: List[StepRecord], base_dir: Path) -> str:
    rules_section = _render_rules_section(base_dir)
    author_prompt = _read_optional_text(base_dir, "author_prompt.txt")
    author_schema = _read_optional_text(base_dir, "author_schema.json")
    rows = []
    for record in records:
        request_body = _read_optional_text(base_dir, record.request)
        response_body = _read_optional_text(base_dir, record.response)
        actions_payload = _read_json_optional(base_dir, record.actions)
        element_body = _format_json(_extract_element_payload(actions_payload))
        click_points = _extract_click_points(actions_payload, record.viewport)
        overlay_html = _render_overlay(click_points)
        parsed_text_body = _format_json(_extract_parsed_text(response_body))
        parsed_actions_body = _format_json(_extract_parsed_actions(actions_payload))
        rows.append(
            f"""
            <section class=\"step\">
              <header>
                <h2>Step {record.index}</h2>
                <div class=\"meta\">{record.url}</div>
              </header>
              <div class=\"body\">
                <figure class=\"shot\">
                  <img src=\"{record.screenshot}\" alt=\"Step {record.index} screenshot\" />
                  {overlay_html}
                </figure>
                <div class=\"payloads\">
                  {_render_payload("Parsed CUA Text", parsed_text_body)}
                  {_render_payload("Parsed CUA Actions", parsed_actions_body)}
                  {_render_payload("Request (full)", request_body, collapsible=True)}
                  {_render_payload("Response (full)", response_body, collapsible=True)}
                  {_render_payload("Captured Element", element_body, collapsible=True)}
                </div>
              </div>
            </section>
            """
        )

    return f"""
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>CUA Run Report</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; margin: 0; background: #f5f2ee; color: #1e1a16; }}
    header.page {{ padding: 24px 32px; background: #1e1a16; color: #f5f2ee; }}
    header.page h1 {{ margin: 0 0 4px; font-size: 22px; }}
    header.page p {{ margin: 0; opacity: 0.7; }}
    main {{ padding: 24px 32px 48px; display: grid; gap: 24px; }}
    section.step {{ background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 6px 20px rgba(0,0,0,0.08); }}
    section.step header h2 {{ margin: 0 0 6px; font-size: 18px; }}
    .meta {{ font-size: 12px; color: #5e5146; word-break: break-all; }}
    figure {{ margin: 12px 0; }}
    figure.shot {{ position: relative; }}
    img {{ width: 100%; border-radius: 10px; border: 1px solid #eee; }}
    .overlay {{ position: absolute; inset: 0; pointer-events: none; }}
    .dot {{ position: absolute; width: 18px; height: 18px; margin-left: -9px; margin-top: -9px; border-radius: 50%; background: rgba(255,59,48,0.45); box-shadow: 0 0 0 2px #fff, 0 0 0 6px rgba(255,59,48,0.2); }}
    .dot[data-kind=\"click\"] {{ background: rgba(255,59,48,0.45); }}
    .dot[data-kind=\"other\"] {{ background: rgba(10,132,255,0.45); }}
    .payloads {{ display: grid; gap: 12px; }}
    .payload {{ background: #faf7f4; border: 1px solid #e2d8cd; border-radius: 8px; padding: 10px; }}
    .payload details {{ margin: 0; }}
    .payload summary {{ cursor: pointer; font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: #5e5146; }}
    .payload h3 {{ margin: 0 0 8px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: #5e5146; }}
    .payload pre {{ margin: 0; font-size: 12px; line-height: 1.4; white-space: pre-wrap; word-break: break-word; }}
    .rules {{ background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 6px 20px rgba(0,0,0,0.08); }}
    .rules h2 {{ margin: 0 0 8px; font-size: 18px; }}
    .rules pre {{ margin: 0; font-size: 12px; line-height: 1.4; white-space: pre-wrap; word-break: break-word; }}
    .code-block {{ position: relative; max-height: 100px; overflow: hidden; border-radius: 6px; }}
    .code-block.expanded {{ max-height: none; }}
    .expand-row {{ margin-top: 8px; font-size: 12px; color: #5e5146; cursor: pointer; user-select: none; }}
    .expand-row:hover {{ text-decoration: underline; }}
    .tabs {{ display: block; }}
    .tabs > input {{ display: none; }}
    .tabs > label {{ display: inline-block; padding: 8px 14px; margin-right: 8px; border-radius: 999px; background: #ede7e1; color: #5e5146; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; cursor: pointer; }}
    .tabs > input:checked + label {{ background: #1e1a16; color: #f5f2ee; }}
    .tab-panel {{ display: none; margin-top: 18px; }}
    #tab-cua:checked ~ #panel-cua {{ display: grid; gap: 24px; }}
    #tab-author:checked ~ #panel-author {{ display: grid; gap: 24px; }}
  </style>
</head>
<body>
  <header class=\"page\">
    <h1>CUA Run Report</h1>
    <p>Steps captured by the Gemini CUA harness</p>
  </header>
  <main>
    <div class=\"tabs\">
      <input type=\"radio\" id=\"tab-cua\" name=\"tabs\" checked />
      <label for=\"tab-cua\">CUA</label>
      <input type=\"radio\" id=\"tab-author\" name=\"tabs\" />
      <label for=\"tab-author\">Authoring</label>
      <div class=\"tab-panel\" id=\"panel-cua\">
        {"".join(rows)}
      </div>
      <div class=\"tab-panel\" id=\"panel-author\">
        {rules_section}
        {_render_author_prompt(author_prompt)}
        {_render_author_schema(author_schema)}
      </div>
    </div>
  </main>
  <script>
    function initExpanders() {{
      document.querySelectorAll('[data-expand]').forEach(function(row) {{
        const targetId = row.getAttribute('data-expand');
        const target = document.getElementById(targetId);
        if (!target) return;

        const always = row.hasAttribute('data-expand-always');
        const hasOverflow = target.scrollHeight > target.clientHeight + 1;
        if (!always && !hasOverflow) {{
          row.style.display = 'none';
          return;
        }}

        row.addEventListener('click', function() {{
          const expanded = target.classList.toggle('expanded');
          row.textContent = expanded ? 'Collapse' : 'Expand';
        }});
      }});
    }}

    window.addEventListener('load', function() {{
      window.requestAnimationFrame(initExpanders);
    }});
  </script>
</body>
</html>
"""


_BLOCK_COUNTER = 0


def _next_block_id() -> str:
    global _BLOCK_COUNTER
    _BLOCK_COUNTER += 1
    return f"block-{_BLOCK_COUNTER}"


def _render_payload(title: str, body: str, collapsible: bool = False) -> str:
    block_id = _next_block_id()
    if collapsible:
        return f"""
        <div class=\"payload\">
          <details>
            <summary>{html.escape(title)}</summary>
            <div class=\"code-block\" id=\"{block_id}\">
              <pre>{html.escape(body)}</pre>
            </div>
            <div class=\"expand-row\" data-expand=\"{block_id}\">Expand</div>
          </details>
        </div>
        """
    return f"""
    <div class=\"payload\">
      <h3>{html.escape(title)}</h3>
      <div class=\"code-block\" id=\"{block_id}\">
        <pre>{html.escape(body)}</pre>
      </div>
      <div class=\"expand-row\" data-expand=\"{block_id}\">Expand</div>
    </div>
    """


def _read_optional_text(base_dir: Path, rel_path: Optional[str]) -> str:
    if not rel_path:
        return "(missing)"
    try:
        path = base_dir / rel_path
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"(failed to load: {exc})"


def _read_json_optional(base_dir: Path, rel_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not rel_path:
        return None
    try:
        path = base_dir / rel_path
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _render_rules_section(base_dir: Path) -> str:
    rules_path = base_dir / "rules.json"
    if not rules_path.exists():
        return "<section class=\"rules\"><h2>Authored Rules</h2><pre>(no rules found)</pre></section>"
    try:
        payload = json.loads(rules_path.read_text(encoding="utf-8"))
        body = json.dumps(payload, indent=2, ensure_ascii=True)
    except Exception as exc:
        body = f"(failed to load rules: {exc})"
    return f"""
    <section class=\"rules\">
      <h2>Authored Rules</h2>
      <pre>{html.escape(body)}</pre>
    </section>
    """


def _render_author_prompt(prompt_text: str) -> str:
    if not prompt_text or prompt_text == "(missing)":
        body = "(no authoring prompt found)"
    else:
        body = prompt_text
    block_id = _next_block_id()
    return f"""
    <section class=\"rules\">
      <h2>Authoring Prompt</h2>
      <div class=\"code-block\" id=\"{block_id}\">
        <pre>{html.escape(body)}</pre>
      </div>
      <div class=\"expand-row\" data-expand=\"{block_id}\" data-expand-always>Expand</div>
    </section>
    """


def _render_author_schema(schema_text: str) -> str:
    if not schema_text or schema_text == "(missing)":
        body = "(no authoring schema found)"
    else:
        body = schema_text
    block_id = f"block-{abs(hash((body, 'schema'))) % 100000000}"
    return f"""
    <section class=\"rules\">
      <h2>Authoring Schema</h2>
      <div class=\"code-block\" id=\"{block_id}\">
        <pre>{html.escape(body)}</pre>
      </div>
      <div class=\"expand-row\" data-expand=\"{block_id}\" data-expand-always>Expand</div>
    </section>
    """


def _format_json(payload: Any) -> str:
    if payload is None:
        return "(missing)"
    try:
        return json.dumps(payload, indent=2, ensure_ascii=True)
    except Exception:
        return str(payload)


def _extract_parsed_text(response_body: str) -> Dict[str, Any]:
    if not response_body or response_body == "(missing)":
        return {"note": "no response body"}
    try:
        payload = json.loads(response_body)
    except Exception:
        return {"note": "response body is not JSON"}
    candidates = payload.get("candidates") or []
    if not candidates:
        return {"note": "no candidates"}
    content = (candidates[0] or {}).get("content") or {}
    parts = content.get("parts") or []
    items: List[Dict[str, Any]] = []
    for part in parts:
        text = part.get("text")
        if text:
            items.append({"text": text, "thought": bool(part.get("thought"))})
    return {"parts": items} if items else {"note": "no text parts"}


def _extract_parsed_actions(actions_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not actions_payload:
        return {"note": "no actions payload"}
    actions = actions_payload.get("actions") or []
    return {"actions": actions}


def _extract_element_payload(actions_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not actions_payload:
        return {"note": "no actions payload"}
    elements = []
    for result in actions_payload.get("results", []):
        payload = result.get("result") or {}
        click = payload.get("click")
        if not click:
            continue
        elements.append(
            {
                "action": result.get("name"),
                "click": click,
            }
        )
    if not elements:
        return {"note": "no click captures in this step"}
    return {"clicks": elements}


def _extract_click_points(actions_payload: Optional[Dict[str, Any]], viewport: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not actions_payload:
        return []
    width = viewport.get("width") or 0
    height = viewport.get("height") or 0
    if not width or not height:
        return []

    points: List[Dict[str, Any]] = []
    for result in actions_payload.get("results", []):
        payload = result.get("result") or {}
        click = payload.get("click")
        if not click:
            continue
        resolved = click.get("resolved") or {}
        x = resolved.get("x")
        y = resolved.get("y")
        if x is None or y is None:
            continue
        points.append(
            {
                "kind": "click",
                "x_pct": (float(x) / float(width)) * 100.0,
                "y_pct": (float(y) / float(height)) * 100.0,
                "label": result.get("name", "click"),
            }
        )
    return points


def _render_overlay(points: List[Dict[str, Any]]) -> str:
    if not points:
        return ""
    dots = []
    for point in points:
        dots.append(
            f"<span class=\"dot\" data-kind=\"{point['kind']}\" "
            f"style=\"left: {point['x_pct']:.2f}%; top: {point['y_pct']:.2f}%;\" "
            f"title=\"{html.escape(str(point.get('label', '')))}\"></span>"
        )
    return f"<div class=\"overlay\">{''.join(dots)}</div>"


def load_step_records(run_dir: Path) -> List[StepRecord]:
    index_path = run_dir / "steps" / "index.json"
    if not index_path.exists():
        return []
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    records: List[StepRecord] = []
    for raw in payload.get("steps", []):
        records.append(
            StepRecord(
                index=int(raw.get("index", 0)),
                url=raw.get("url", ""),
                viewport=raw.get("viewport", {}),
                screenshot=raw.get("screenshot", ""),
                request=raw.get("request"),
                response=raw.get("response"),
                actions=raw.get("actions"),
                ts=float(raw.get("ts", 0.0)),
                notes=raw.get("notes"),
            )
        )
    return records


def build_report_from_run(run_dir: Path) -> Path:
    records = load_step_records(run_dir)
    report_path = run_dir / "report.html"
    report_path.write_text(_build_report_html(records, run_dir), encoding="utf-8")
    return report_path
