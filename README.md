# CUA Exploration Skeleton (Gemini)

A minimal, inspectable harness for experimenting with Gemini Computer Use + Playwright.

## Goals
- Drive a browser with CUA actions
- Capture element info at click coordinates (for later rule extraction)
- Save per-PDP logs as human-readable JSON

## Architecture (Data Separation)
The system keeps **model-facing data** and **local artifacts** completely separate.

### Model-facing (sent to Gemini)
Minimum required info to maintain the CUA loop:
- **Screenshot** of the current viewport (per step)
- **Tool results** from the last executed actions (status + url only)

No element/ancestry info is ever sent to Gemini.

### Local-only (never sent to Gemini)
- Element + ancestry captures at click points
- Full step logs (request/response/actions payloads)
- Screenshots saved to disk
- PDP JSON files
- Authored rules (`rules.json`)

## Setup
```bash
uv venv
uv sync
uv run python -m playwright install chromium
```

Set your API key:
```bash
export GEMINI_API_KEY="your-key"
```

## Run (Gemini CUA)
```bash
PYTHONPATH=src uv run python -m cua.cli \
  --start-url https://www.nike.com \
  --out-dir outputs \
  --stage cua
```

Optional flags:
- `--cua-model`: override the **CUA model** name (default: `gemini-2.5-computer-use-preview-10-2025`)
- `--goal`: custom instructions for the CUA agent
- `--exclude-action`: exclude a CUA action (repeatable)
- `--run-name`: optional run folder name (auto-suffixed if it exists)
- `--author-model`: override the **authoring model** name (default: `gemini-3-flash-preview`)
- `--min-variantless-pdp`: minimum PDPs without variants (default: `0`)
- `--min-variant-pdp`: minimum PDPs with variants (default: `1`)
- `--max-pdp`: maximum total PDPs to capture (default: `2`)
- `--wait-load-state`: load state to wait for after each action (default: `load`)
- `--wait-timeout-ms`: timeout for the load-state wait (default: `5000`)
- `--post-action-sleep`: extra sleep seconds after the load-state wait (default: `1.0`)

## Run stages
The CLI supports these stages:
- `--stage cua` (CUA only)
- `--stage author` (author rules from an existing run folder)
- `--stage cua+author` (run CUA, then author rules)
- `--stage report` (rebuild report from an existing run folder)

Author-only example:
```bash
PYTHONPATH=src uv run python -m cua.cli \
  --stage author \
  --run-dir outputs/<host>/<run_name> \
  --author-model gemini-3-flash-preview
```

CUA + author example:
```bash
PYTHONPATH=src uv run python -m cua.cli \
  --stage cua+author \
  --start-url https://www.nike.com \
  --min-variant-pdp 1 \
  --min-variantless-pdp 0 \
  --max-pdp 2 \
  --out-dir outputs
```

Report-only example (no CUA run):
```bash
PYTHONPATH=src uv run python -m cua.cli \
  --stage report \
  --run-dir outputs/<host>/<run_name>
```

Outputs land in `outputs/<host>/<run_name>/pdps/pdp_001.json`, `pdp_002.json`, ...
Each run is isolated in `outputs/<host>/<run_name>/` with a `report.html` and per-step logs.
If a run folder already exists, a numeric suffix is appended.

Open `report.html` in a browser to review step screenshots and JSON logs.
If you run the authoring stage, `rules.json` is written to the run folder and is embedded in the report.

`rules.json` schema (current):
- `pdp_url_regex` + `pdp_url_reason`
- `add_to_cart_selector` + `add_to_cart_selector_reason`
- `clickable_js` + `clickable_js_reason`
- `assertion_proposal` + `assertion_proposal_reason`
- `variant_extraction` (groups with selectors + reasoning for variant option, text, image URL, and availability/disabled state)

Rule authoring uses an LLM (default `gemini-3-flash-preview`) and requires `GEMINI_API_KEY`.
Structured JSON enforcement uses `response_mime_type=application/json` with a JSON Schema.

If the model requests `require_confirmation`, the CLI will prompt you before executing the action.

Run folders are self-contained for later analysis: they include step logs (request/response/actions), PDP JSONs with element ancestry, and screenshots. This is enough to rehydrate state and author selector rules without any replay tooling.

## Next Steps
- Add a post-hoc analysis step to generate lightweight selectors.

## Project Layout
- `src/cua/cli.py` — CLI entrypoint
- `src/cua/session.py` — main control loop
- `src/cua/browser.py` — Playwright helpers
- `src/cua/capture.py` — element capture at (x, y)
- `src/cua/models.py` — model adapters (Gemini)
- `src/cua/output.py` — per-PDP JSON writer
- `src/cua/cobrowse.py` — co-browse rule evaluator

## Co-browse (rules evaluation)
```bash
PYTHONPATH=src uv run python -m cua.cobrowse \
  --run-dir outputs/<host>/<run_name> \
  --url https://www.nike.com \
  --interval 1
```
