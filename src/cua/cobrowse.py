from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import Page, sync_playwright


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Co-browse and evaluate authored rules")
    parser.add_argument("--run-dir", required=True, help="Run folder containing rules.json")
    parser.add_argument("--url", help="Optional URL to open")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_dir = Path(args.run_dir)
    rules_path = run_dir / "rules.json"
    if not rules_path.exists():
        raise SystemExit(f"rules.json not found in {run_dir}")

    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    rule_payload = rules.get("rules") or {}

    pdp_regex = rule_payload.get("pdp_url_regex")
    add_to_cart_selector = rule_payload.get("add_to_cart_selector")
    clickable_js = rule_payload.get("clickable_js")
    variant_groups = (rule_payload.get("variant_extraction") or {}).get("groups", [])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        if args.url:
            page.goto(args.url, wait_until="domcontentloaded")
        else:
            page.goto("about:blank")

        try:
            while True:
                status = evaluate_rules(page, pdp_regex, add_to_cart_selector, clickable_js, variant_groups)
                print(json.dumps(status, indent=2, ensure_ascii=True), flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass
        finally:
            context.close()
            browser.close()


def evaluate_rules(
    page: Page,
    pdp_regex: Optional[str],
    add_to_cart_selector: Optional[str],
    clickable_js: Optional[str],
    variant_groups: List[Dict[str, Any]],
) -> Dict[str, Any]:
    url = page.url
    is_pdp = False
    if pdp_regex:
        try:
            is_pdp = page.evaluate("(url, pattern) => new RegExp(pattern).test(url)", url, pdp_regex)
        except Exception:
            is_pdp = False

    add_to_cart_found = False
    clickable_result = None
    clickable_error = None
    if add_to_cart_selector:
        try:
            add_to_cart_found = page.query_selector(add_to_cart_selector) is not None
        except Exception:
            add_to_cart_found = False

    if add_to_cart_selector and clickable_js:
        try:
            clickable_result = page.evaluate(
                "({ selector, expr }) => { const el = document.querySelector(selector); if (!el) return null; return !!(function(el){ return eval(expr); })(el); }",
                {"selector": add_to_cart_selector, "expr": clickable_js},
            )
        except Exception as exc:
            clickable_result = None
            clickable_error = str(exc)

    variants = []
    for group in variant_groups:
        variants.append(_extract_variant_group(page, group))

    return {
        "url": url,
        "is_pdp": is_pdp,
        "add_to_cart_found": add_to_cart_found,
        "clickable": clickable_result,
        "clickable_error": clickable_error,
        "variants": variants,
    }


def _extract_variant_group(page: Page, group: Dict[str, Any]) -> Dict[str, Any]:
    selector = group.get("variant_selector")
    if not selector:
        return {"group_type": group.get("group_type"), "error": "missing variant_selector"}

    text_selector = group.get("variant_text_selector")
    image_selector = group.get("variant_image_selector")
    availability_selector = group.get("variant_availability_selector")

    try:
        items = page.query_selector_all(selector)
    except Exception:
        items = []

    extracted: List[Dict[str, Any]] = []
    for item in items:
        text = None
        image = None
        availability = None
        try:
            if text_selector:
                el = item.query_selector(text_selector)
                text = el.inner_text() if el else None
            if image_selector:
                img = item.query_selector(image_selector)
                if img:
                    image = img.get_attribute("src") or img.get_attribute("data-src")
            if availability_selector:
                avail_el = item.query_selector(availability_selector)
                if avail_el:
                    availability = avail_el.inner_text()
        except Exception:
            pass
        extracted.append({"text": text, "image": image, "availability": availability})

    return {
        "group_type": group.get("group_type"),
        "count": len(extracted),
        "variants": extracted,
    }


if __name__ == "__main__":
    main()
