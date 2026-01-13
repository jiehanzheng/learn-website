from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from playwright.sync_api import Page

from cua.browser import BrowserHarness
from cua.capture import capture_element_at
from cua.models import Action, ModelAdapter, SUPPORTED_ACTIONS
from cua.output import PdpWriter
from cua.run import RunLogger, create_run_logger


@dataclass
class CuaSession:
    start_url: str
    min_variantless_pdp: int
    min_variant_pdp: int
    max_pdp: int
    out_dir: Any
    model_adapter: ModelAdapter
    headless: bool = False
    normalize_coords: bool = True
    run_name: str | None = None
    wait_load_state: str = "load"
    wait_timeout_ms: int = 5000
    post_action_sleep: float = 1.0

    def run(self) -> Path:
        harness = BrowserHarness(headless=self.headless)
        page = harness.start()
        run_logger: RunLogger | None = None
        run_root: Path | None = None
        try:
            page.goto(self.start_url, wait_until="domcontentloaded")
            self._wait_for_settle(page)
            host = urlparse(self.start_url).netloc or "site"
            run_logger = create_run_logger(Path(self.out_dir), host, self.run_name)
            run_root = run_logger.root
            writer = PdpWriter(run_logger.pdps_dir)
            run_logger.write_run_info(
                self._build_run_info(host)
            )

            pdp_index = 1
            variant_pdp_count = 0
            variantless_pdp_count = 0
            writer.start(pdp_index, page.url)
            last_action_results: List[Dict[str, Any]] = []

            while pdp_index <= self.max_pdp:
                snapshot = self._capture_local_snapshot(page, harness)
                step_record = run_logger.next_step(
                    url=snapshot["url"],
                    viewport=snapshot["viewport"],
                    screenshot_bytes=snapshot["screenshot"],
                    ts=time.time(),
                )
                model_context = self._build_model_context(snapshot, last_action_results)
                actions = self.model_adapter.next_actions(model_context)
                trace = self.model_adapter.get_last_trace()
                if trace:
                    run_logger.write_request(step_record, trace.get("request", {}))
                    run_logger.write_response(step_record, trace.get("response", {}))
                    self._print_trace(trace, actions)
                if not actions:
                    break

                last_action_results = []
                report_results: List[Dict[str, Any]] = []
                for action in actions:
                    if action.name not in SUPPORTED_ACTIONS:
                        step = {
                            "action": action.name,
                            "args": dict(action.args),
                            "ts": time.time(),
                            "error": f"Unsupported action: {action.name}",
                            "duration_ms": 0,
                        }
                        writer.add_step(step)
                        last_action_results.append(
                            {"name": action.name, "call_id": action.call_id, "result": {"error": step["error"]}}
                        )
                        continue

                    if action.name == "pdp_complete":
                        step = {
                            "action": action.name,
                            "args": dict(action.args),
                            "ts": time.time(),
                            "duration_ms": 0,
                        }
                        writer.add_step(step)
                        has_variants = bool(action.args.get("has_variants", False))
                        if has_variants:
                            variant_pdp_count += 1
                        else:
                            variantless_pdp_count += 1
                        last_action_results.append(
                            {"name": action.name, "call_id": action.call_id, "result": {"status": "ok"}}
                        )
                        writer.finish()
                        pdp_index += 1
                        if self._meets_pdp_targets(variant_pdp_count, variantless_pdp_count):
                            run_logger.write_report()
                            return run_root
                        writer.start(pdp_index, page.url)
                        continue

                    if action.name == "finish":
                        step = {
                            "action": action.name,
                            "args": dict(action.args),
                            "ts": time.time(),
                            "duration_ms": 0,
                        }
                        writer.add_step(step)
                        run_logger.write_report()
                        return run_root

                    step = self._execute_action(page, harness, action)
                    if action.name != "wait_5_seconds":
                        self._wait_for_settle(page)
                    writer.add_step(step)
                    result_payload = {"status": "ok", "url": page.url}
                    if "error" in step:
                        result_payload = {"error": step["error"], "url": page.url}
                    if "safety_acknowledgement" in step:
                        result_payload["safety_acknowledgement"] = step["safety_acknowledgement"]
                    last_action_results.append(
                        {"name": action.name, "call_id": action.call_id, "result": result_payload}
                    )
                    report_payload = dict(result_payload)
                    if "click" in step:
                        report_payload["click"] = step["click"]
                    report_results.append(
                        {"name": action.name, "call_id": action.call_id, "result": report_payload}
                    )
                    if step.get("safety_decision") == "require_confirmation" and "safety_acknowledgement" not in step:
                        run_logger.write_report()
                        return run_root
                run_logger.write_actions(
                    step_record,
                    {
                        "actions": [action.__dict__ for action in actions],
                        "results": report_results,
                    },
                )
            if run_root is None:
                raise RuntimeError("Run directory was not created")
            return run_root
        finally:
            if run_logger:
                run_logger.write_report()
            harness.stop()

    def _capture_local_snapshot(self, page: Page, harness: BrowserHarness) -> Dict[str, Any]:
        return {
            "url": page.url,
            "viewport": harness.viewport_size(),
            "screenshot": harness.screenshot(),
        }

    def _build_model_context(
        self,
        snapshot: Dict[str, Any],
        last_action_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "screenshot": snapshot["screenshot"],
            "last_action_results": last_action_results,
        }

    def _build_run_info(self, host: str) -> Dict[str, Any]:
        info = {
            "started_at": datetime.now().isoformat(),
            "start_url": self.start_url,
            "host": host,
            "model_adapter": type(self.model_adapter).__name__,
            "min_variantless_pdp": self.min_variantless_pdp,
            "min_variant_pdp": self.min_variant_pdp,
            "max_pdp": self.max_pdp,
        }
        model_name = getattr(self.model_adapter, "model_name", None)
        if model_name:
            info["model_name"] = model_name
        return info

    def _execute_action(self, page: Page, harness: BrowserHarness, action: Action) -> Dict[str, Any]:
        start = time.time()
        name = action.name
        args = dict(action.args)
        step: Dict[str, Any] = {"action": name, "args": args, "ts": start}

        safety_decision = self._extract_safety_decision(args)
        if safety_decision == "require_confirmation":
            confirmed = self._prompt_confirmation(action)
            step["safety_decision"] = safety_decision
            if not confirmed:
                step["error"] = "User denied required confirmation."
                step["duration_ms"] = int((time.time() - start) * 1000)
                return step
            step["safety_acknowledgement"] = "true"

        if name == "open_web_browser":
            pass
        elif name == "navigate":
            page.goto(args["url"], wait_until="domcontentloaded")
        elif name == "go_back":
            page.go_back(wait_until="domcontentloaded")
        elif name == "go_forward":
            page.go_forward(wait_until="domcontentloaded")
        elif name == "click_at":
            x, y, raw = self._normalize_coords(args, harness)
            capture = None
            try:
                capture = capture_element_at(page, x, y)
            except Exception as exc:
                step["click_capture_error"] = str(exc)
            page.mouse.click(x, y)
            step["click"] = {
                "raw": raw,
                "resolved": {"x": x, "y": y},
                "element": capture,
                "url": page.url,
                "viewport": harness.viewport_size(),
            }
        elif name == "type_text_at":
            x, y, _ = self._normalize_coords(args, harness)
            text = args.get("text", "")
            page.mouse.click(x, y)
            if args.get("clear_before_typing", True):
                modifier = "Meta" if sys.platform == "darwin" else "Control"
                page.keyboard.press(f"{modifier}+A")
                page.keyboard.press("Backspace")
            if text:
                page.keyboard.type(text)
            if args.get("press_enter", True):
                page.keyboard.press("Enter")
        elif name == "hover_at":
            x, y, _ = self._normalize_coords(args, harness)
            page.mouse.move(x, y)
        elif name == "key_combination":
            keys = args.get("keys") or ""
            if keys:
                page.keyboard.press(keys)
        elif name == "scroll_document":
            direction = args.get("direction", "down")
            magnitude = args.get("magnitude", 800)
            dx, dy = self._scroll_delta(direction, magnitude, harness)
            page.mouse.wheel(dx, dy)
        elif name == "scroll_at":
            x, y, _ = self._normalize_coords(args, harness)
            direction = args.get("direction", "down")
            magnitude = args.get("magnitude", 800)
            dx, dy = self._scroll_delta(direction, magnitude, harness)
            page.mouse.move(x, y)
            page.mouse.wheel(dx, dy)
        elif name == "drag_and_drop":
            x, y, _ = self._normalize_coords(args, harness)
            dest_x, dest_y, _ = self._normalize_xy(
                float(args.get("destination_x", 0)),
                float(args.get("destination_y", 0)),
                harness,
            )
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(dest_x, dest_y)
            page.mouse.up()
        elif name == "search":
            query = args.get("query", "")
            page.goto("https://www.google.com", wait_until="domcontentloaded")
            if query:
                try:
                    page.fill("input[name='q']", query)
                    page.keyboard.press("Enter")
                except Exception:
                    pass
        elif name == "scroll":
            page.mouse.wheel(args.get("dx", 0), args.get("dy", 0))
        elif name == "wait_5_seconds":
            page.wait_for_timeout(5000)
        else:
            step["error"] = f"Unknown action: {name}"

        step["duration_ms"] = int((time.time() - start) * 1000)
        return step

    def _extract_safety_decision(self, args: Dict[str, Any]) -> str | None:
        if "safety_decision" in args:
            value = args["safety_decision"]
            if isinstance(value, dict):
                return value.get("decision")
            if isinstance(value, str):
                return value
        return None

    def _prompt_confirmation(self, action: Action) -> bool:
        prompt = (
            f"Model requested confirmation for action '{action.name}'.\n"
            f"Args: {action.args}\n"
            "Proceed? [y/N]: "
        )
        try:
            response = input(prompt)
        except EOFError:
            return False
        return response.strip().lower() in {"y", "yes"}

    def _wait_for_settle(self, page: Page) -> None:
        try:
            page.wait_for_load_state(self.wait_load_state, timeout=self.wait_timeout_ms)
        except Exception:
            pass
        if self.post_action_sleep > 0:
            time.sleep(self.post_action_sleep)

    def _meets_pdp_targets(self, variant_pdp: int, variantless_pdp: int) -> bool:
        return variant_pdp >= self.min_variant_pdp and variantless_pdp >= self.min_variantless_pdp


    def _print_trace(self, trace: Dict[str, Any], actions: List[Action]) -> None:
        print("\n=== CUA Step ===", flush=True)
        response_text = trace.get("response_text") or []
        if response_text:
            print("Model text:", flush=True)
            for item in response_text:
                prefix = "[thought] " if item.get("thought") else ""
                print(f"- {prefix}{item.get('text')}", flush=True)
        else:
            print("Model text: (none)", flush=True)
        if actions:
            print("Actions:", flush=True)
            for action in actions:
                print(f"- {action.name} {action.args}", flush=True)
        else:
            print("Actions: (none)", flush=True)

    def _normalize_coords(self, args: Dict[str, Any], harness: BrowserHarness) -> tuple[float, float, Dict[str, Any]]:
        x = float(args.get("x", 0))
        y = float(args.get("y", 0))
        return self._normalize_xy(x, y, harness)

    def _normalize_xy(self, x: float, y: float, harness: BrowserHarness) -> tuple[float, float, Dict[str, Any]]:
        raw = {"x": x, "y": y, "normalized": False}
        if self.normalize_coords:
            viewport = harness.viewport_size()
            width = viewport["width"]
            height = viewport["height"]
            if 0 <= x <= 1000 and 0 <= y <= 1000:
                raw["normalized"] = True
                x = (x / 1000.0) * width
                y = (y / 1000.0) * height
        return x, y, raw

    def _scroll_delta(self, direction: str, magnitude: float, harness: BrowserHarness) -> tuple[float, float]:
        viewport = harness.viewport_size()
        width = viewport["width"]
        height = viewport["height"]
        delta = magnitude
        if self.normalize_coords and 0 <= magnitude <= 1000:
            if direction in {"left", "right"}:
                delta = (magnitude / 1000.0) * width
            else:
                delta = (magnitude / 1000.0) * height

        if direction == "up":
            return 0, -delta
        if direction == "left":
            return -delta, 0
        if direction == "right":
            return delta, 0
        return 0, delta
