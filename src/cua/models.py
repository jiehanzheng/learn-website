from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types


COMPUTER_USE_ACTIONS = {
    "open_web_browser",
    "wait_5_seconds",
    "go_back",
    "go_forward",
    "search",
    "navigate",
    "click_at",
    "hover_at",
    "type_text_at",
    "key_combination",
    "scroll_document",
    "scroll_at",
    "drag_and_drop",
    "scroll",
}

CUSTOM_ACTIONS = {"pdp_complete", "finish"}

SUPPORTED_ACTIONS = COMPUTER_USE_ACTIONS | CUSTOM_ACTIONS


@dataclass
class Action:
    name: str
    args: Dict[str, Any]
    note: Optional[str] = None
    call_id: Optional[str] = None


class ModelAdapter:
    def next_actions(self, context: Dict[str, Any]) -> List[Action]:
        raise NotImplementedError

    def get_last_trace(self) -> Optional[Dict[str, Any]]:
        return None


class GeminiCuaAdapter(ModelAdapter):
    def __init__(
        self,
        model_name: str,
        goal: str,
        exclude_actions: Optional[List[str]] = None,
        temperature: float = 0.2,
    ) -> None:
        self.model_name = model_name
        self.goal = goal
        self.exclude_actions = exclude_actions or []
        self.temperature = temperature
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        self._contents: List[types.Content] = []
        self._last_trace: Optional[Dict[str, Any]] = None
        self._config = types.GenerateContentConfig(
            system_instruction=(
        "You are a browser automation agent. Use the provided tools to act on the page. "
        "Only call supported actions. For each PDP, click the Add to Cart button, then call "
        "`pdp_complete` with an argument has_variants=true or false. "
        "Ensure you collect PDPs with and without variants according to the user's targets. "
        "For variant PDPs, click multiple variant options (size/color/etc.) to capture their elements. "
        "After all required PDPs are done, call `finish`."
    ),
            temperature=self.temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                        excluded_predefined_functions=self.exclude_actions,
                    )
                ),
                types.Tool(function_declarations=_custom_function_declarations()),
            ],
        )

    def next_actions(self, context: Dict[str, Any]) -> List[Action]:
        if not self._contents:
            parts, snapshot_parts = self._build_initial_parts(context)
            self._contents.append(types.Content(role="user", parts=parts))
            self._last_trace = {
                "request": self._build_request_snapshot(snapshot_parts),
            }
        else:
            last_results = context.get("last_action_results") or []
            if last_results:
                parts, snapshot_parts = _build_function_response_parts(last_results, context.get("screenshot"))
                self._contents.append(types.Content(role="user", parts=parts))
                self._last_trace = {
                    "request": self._build_request_snapshot(snapshot_parts),
                }

        response = self._client.models.generate_content(
            model=self.model_name,
            contents=self._contents,
            config=self._config,
        )

        if self._last_trace is None:
            self._last_trace = {}
        self._last_trace["response"] = response.model_dump(mode="json")
        self._last_trace["response_text"] = _extract_response_text(response)

        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content:
            return []

        self._contents.append(candidate.content)
        actions: List[Action] = []
        for part in candidate.content.parts or []:
            if not part.function_call:
                continue
            function_call = part.function_call
            name = function_call.name or ""
            args = function_call.args or {}
            actions.append(Action(name=name, args=args, call_id=function_call.id))
        return actions

    def get_last_trace(self) -> Optional[Dict[str, Any]]:
        return self._last_trace

    def _build_initial_parts(self, context: Dict[str, Any]) -> tuple[List[types.Part], List[Dict[str, Any]]]:
        parts = [types.Part.from_text(text=self.goal)]
        snapshot_parts = [{"text": self.goal}]
        screenshot = context.get("screenshot")
        if screenshot:
            parts.append(types.Part.from_bytes(data=screenshot, mime_type="image/png"))
            snapshot_parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "size_bytes": len(screenshot),
                    }
                }
            )
        return parts, snapshot_parts

    def _build_request_snapshot(self, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        system_instruction = self._config.system_instruction
        if hasattr(system_instruction, "model_dump"):
            system_instruction = system_instruction.model_dump(mode="json")
        contents_dump = []
        for content in self._contents:
            if hasattr(content, "model_dump"):
                contents_dump.append(_redact_inline_data(content.model_dump(mode="json")))
            else:
                contents_dump.append(_redact_inline_data(content))
        config_dump = self._config.model_dump(mode="json") if hasattr(self._config, "model_dump") else None
        return {
            "model": self.model_name,
            "system_instruction": system_instruction,
            "temperature": self.temperature,
            "exclude_actions": self.exclude_actions,
            "config": config_dump,
            "contents": contents_dump,
            "new_content": {
                "role": "user",
                "parts": parts,
            },
            "history_count": len(self._contents),
        }


def _extract_response_text(response: types.GenerateContentResponse) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    candidate = response.candidates[0] if response.candidates else None
    if not candidate or not candidate.content:
        return items
    for part in candidate.content.parts or []:
        if part.text:
            items.append({"text": part.text, "thought": bool(part.thought)})
    return items


def _redact_inline_data(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_redact_inline_data(item) for item in payload]
    if isinstance(payload, dict):
        redacted: Dict[str, Any] = {}
        for key, value in payload.items():
            if key in {"inline_data", "inlineData"} and isinstance(value, dict):
                inline = dict(value)
                if "data" in inline:
                    inline["data"] = "<omitted>"
                redacted[key] = _redact_inline_data(inline)
            else:
                redacted[key] = _redact_inline_data(value)
        return redacted
    return payload


def _custom_function_declarations() -> List[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name="pdp_complete",
            description="Mark that add-to-cart was clicked on the current PDP.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "has_variants": {
                        "type": "boolean",
                        "description": "Whether this PDP has selectable variants (size/color/etc.).",
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.FunctionDeclaration(
            name="finish",
            description="Signal that the task is complete.",
            parameters_json_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ]


def _build_function_response_parts(
    results: List[Dict[str, Any]],
    screenshot: Optional[bytes],
) -> tuple[List[types.Part], List[Dict[str, Any]]]:
    parts: List[types.Part] = []
    snapshot_parts: List[Dict[str, Any]] = []
    for result in results:
        name = result.get("name")
        if not name:
            continue
        response = result.get("result") or {}

        fr_parts: List[types.FunctionResponsePart] = []
        if screenshot and name in COMPUTER_USE_ACTIONS:
            fr_parts.append(types.FunctionResponsePart.from_bytes(data=screenshot, mime_type="image/png"))

        function_response = types.FunctionResponse(
            name=name,
            response=response,
            id=result.get("call_id"),
            parts=fr_parts or None,
        )
        parts.append(types.Part(function_response=function_response))
        snapshot_parts.append(
            {
                "function_response": {
                    "name": name,
                    "response": response,
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "note": "screenshot attached" if screenshot else "no screenshot",
                            }
                        }
                    ]
                    if screenshot
                    else [],
                }
            }
        )
    return parts, snapshot_parts
