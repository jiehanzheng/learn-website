from __future__ import annotations

import json
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai

RULE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "pdp_url_regex": {
            "type": "string",
            "description": "Regex that matches PDP URLs for the target site.",
        },
        "pdp_url_reason": {
            "type": "string",
            "description": "Reasoning in English for the PDP URL regex.",
        },
        "add_to_cart_selector": {
            "type": "string",
            "description": "A single CSS selector for the Add to Cart button.",
        },
        "add_to_cart_selector_reason": {
            "type": "string",
            "description": "Reasoning in English for the selector.",
        },
        "clickable_js": {
            "type": "string",
            "description": "JS expression that returns truthy when the Add to Cart button is clickable. Use variable name 'el'.",
        },
        "clickable_js_reason": {
            "type": "string",
            "description": "Reasoning in English for the clickable expression.",
        },
        "assertion_proposal": {
            "type": "string",
            "description": "English proposal for client-side assertions after Add to Cart.",
        },
        "assertion_proposal_reason": {
            "type": "string",
            "description": "Reasoning in English for the assertion proposal.",
        },
        "variant_extraction": {
            "type": "object",
            "description": "Variant extraction logic for size/color/etc.",
            "properties": {
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "group_type": {
                                "type": "string",
                                "description": "Variant group type, e.g. size, color, width.",
                            },
                            "group_reason": {
                                "type": "string",
                                "description": "Reasoning for why this group is a variant selector.",
                            },
                            "variant_selector": {
                                "type": "string",
                                "description": "Selector that matches each variant option.",
                            },
                            "variant_selector_reason": {
                                "type": "string",
                                "description": "Reasoning for the variant selector.",
                            },
                            "variant_text_selector": {
                                "type": "string",
                                "description": "Selector (relative to variant element) for the variant text.",
                            },
                            "variant_text_selector_reason": {
                                "type": "string",
                                "description": "Reasoning for the variant text selector.",
                            },
                            "variant_image_selector": {
                                "type": "string",
                                "description": "Selector (relative to variant element) for the variant image URL, if available.",
                            },
                            "variant_image_selector_reason": {
                                "type": "string",
                                "description": "Reasoning for the image selector (use empty string if not applicable).",
                            },
                            "variant_availability_selector": {
                                "type": "string",
                                "description": "Selector (relative to variant element) that indicates availability/disabled state.",
                            },
                            "variant_availability_selector_reason": {
                                "type": "string",
                                "description": "Reasoning for the availability selector.",
                            },
                        },
                        "required": [
                            "group_type",
                            "group_reason",
                            "variant_selector",
                            "variant_selector_reason",
                            "variant_text_selector",
                            "variant_text_selector_reason",
                            "variant_image_selector",
                            "variant_image_selector_reason",
                            "variant_availability_selector",
                            "variant_availability_selector_reason",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["groups"],
            "additionalProperties": False,
        },
    },
    "required": [
        "pdp_url_regex",
        "pdp_url_reason",
        "add_to_cart_selector",
        "add_to_cart_selector_reason",
        "clickable_js",
        "clickable_js_reason",
        "assertion_proposal",
        "assertion_proposal_reason",
        "variant_extraction",
    ],
    "additionalProperties": False,
}

DEFAULT_AUTHOR_MODEL = "gemini-3-flash-preview"


def generate_rules(run_dir: Path, model_name: str = DEFAULT_AUTHOR_MODEL) -> Path:
    clicks = _load_click_elements(run_dir)
    prompt = _build_prompt(clicks, run_dir)
    _write_prompt(run_dir, prompt, model_name)
    _write_schema(run_dir)
    rules = _call_model(prompt, model_name=model_name)
    out_path = run_dir / "rules.json"
    out_path.write_text(json.dumps(rules, indent=2, ensure_ascii=True), encoding="utf-8")
    return out_path


def _load_click_elements(run_dir: Path) -> List[Dict[str, Any]]:
    from_steps = _load_clicks_from_steps(run_dir)
    if from_steps:
        return from_steps
    pdp_dir = run_dir / "pdps"
    if not pdp_dir.exists():
        return []
    elements: List[Dict[str, Any]] = []
    for path in sorted(pdp_dir.glob("pdp_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for step in payload.get("steps", []):
            click = step.get("click")
            if not click:
                continue
            element = click.get("element")
            if element:
                elements.append(
                    {
                        "element": element,
                        "url": click.get("url"),
                        "model_text": [],
                        "source": "pdp",
                    }
                )
    return elements


def _build_prompt(clicks: List[Dict[str, Any]], run_dir: Path) -> str:
    data = {
        "run_dir": str(run_dir),
        "click_count": len(clicks),
        "clicks": clicks,
    }
    return (
        "You are a rules authoring model. Produce a JSON object that matches the provided schema.\n"
        "Use the captured click element + ancestry info to infer a single selector for the Add to Cart button.\n"
        "Use the captured PDP URLs to derive a PDP URL regex.\n"
        "Also derive variant extraction logic:\n"
        "- Identify at least one variant group (size, color, etc.) if present.\n"
        "- Provide a selector that matches each variant option.\n"
        "- Provide selectors (relative to the variant option) for text, image URL (if any), and availability/disabled state.\n"
        "Each click may include CUA model text from the step that produced the action.\n"
        "Provide reasoning in English for each field that asks for a reason.\n"
        "Return JSON only. No markdown.\n\n"
        f"Captured data:\n{json.dumps(data, indent=2)}"
    )


def _call_model(prompt: str, model_name: str) -> Dict[str, Any]:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": RULE_SCHEMA,
        },
    )
    if not response.text:
        raise ValueError("Authoring model returned empty response")
    payload = json.loads(response.text)
    return {
        "version": "0.3",
        "created_at": datetime.now().isoformat(),
        "model": model_name,
        "rules": payload,
    }


def _write_prompt(run_dir: Path, prompt: str, model_name: str) -> None:
    path = run_dir / "author_prompt.txt"
    header = f"model: {model_name}\ncreated_at: {datetime.now().isoformat()}\n\n"
    path.write_text(header + prompt, encoding="utf-8")


def _write_schema(run_dir: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    latest_path = run_dir / "author_schema.json"
    history_path = run_dir / f"author_schema_{timestamp}.json"
    payload = json.dumps(RULE_SCHEMA, indent=2, ensure_ascii=True)
    latest_path.write_text(payload, encoding="utf-8")
    history_path.write_text(payload, encoding="utf-8")


def _load_clicks_from_steps(run_dir: Path) -> List[Dict[str, Any]]:
    index_path = run_dir / "steps" / "index.json"
    if not index_path.exists():
        return []
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    steps = payload.get("steps", [])
    results: List[Dict[str, Any]] = []
    for step in steps:
        actions_payload = _read_json_optional(run_dir, step.get("actions"))
        response_payload = _read_json_optional(run_dir, step.get("response"))
        if not actions_payload:
            continue
        model_text = _extract_response_text(response_payload)
        for result in actions_payload.get("results", []):
            click = (result.get("result") or {}).get("click") or {}
            element = click.get("element")
            if not element:
                continue
            resolved = click.get("resolved") or {}
            results.append(
                {
                    "step_index": step.get("index"),
                    "url": click.get("url") or step.get("url"),
                    "action": result.get("name"),
                    "model_text": model_text,
                    "element": element,
                    "click_point": {
                        "x": resolved.get("x"),
                        "y": resolved.get("y"),
                    },
                    "source": "steps",
                }
            )
    return results


def _read_json_optional(run_dir: Path, rel_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not rel_path:
        return None
    try:
        path = run_dir / rel_path
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_response_text(response_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not response_payload:
        return []
    candidates = response_payload.get("candidates") or []
    if not candidates:
        return []
    content = (candidates[0] or {}).get("content") or {}
    parts = content.get("parts") or []
    items: List[Dict[str, Any]] = []
    for part in parts:
        text = part.get("text")
        if text:
            items.append({"text": text, "thought": bool(part.get("thought"))})
    return items
