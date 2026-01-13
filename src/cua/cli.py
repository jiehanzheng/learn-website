import argparse
import pathlib

from cua.author import DEFAULT_AUTHOR_MODEL, generate_rules
from cua.models import GeminiCuaAdapter
from cua.run import build_report_from_run
from cua.session import CuaSession


DEFAULT_CUA_MODEL = "gemini-2.5-computer-use-preview-10-2025"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CUA exploration runner")
    parser.add_argument(
        "--stage",
        choices=["cua", "author", "cua+author", "report"],
        default="cua",
        help="Pipeline stage",
    )
    parser.add_argument("--start-url", help="Starting URL (e.g., https://www.nike.com)")
    parser.add_argument("--run-dir", help="Existing run folder for authoring")
    parser.add_argument("--author-model", default=DEFAULT_AUTHOR_MODEL, help="Model for authoring rules")
    parser.add_argument("--min-variantless-pdp", type=int, default=0, help="Minimum PDPs without variants")
    parser.add_argument("--min-variant-pdp", type=int, default=1, help="Minimum PDPs with variants")
    parser.add_argument("--max-pdp", type=int, default=2, help="Maximum total PDPs to capture")
    parser.add_argument("--out-dir", default="outputs", help="Output directory")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--cua-model", default=DEFAULT_CUA_MODEL, help="CUA model name")
    parser.add_argument("--goal", help="Goal/instructions for the CUA model")
    parser.add_argument("--exclude-action", action="append", default=[], help="Exclude a CUA action")
    parser.add_argument("--run-name", help="Optional run folder name (auto-suffixed if already exists)")
    parser.add_argument(
        "--wait-load-state",
        default="load",
        choices=["load", "domcontentloaded", "networkidle"],
        help="Load state to wait for after each action",
    )
    parser.add_argument("--wait-timeout-ms", type=int, default=5000, help="Timeout for load-state wait")
    parser.add_argument("--post-action-sleep", type=float, default=1.0, help="Sleep seconds after load-state wait")
    parser.add_argument("--normalize-coords", action="store_true", default=True, help="Treat click coords as 0-1000 normalized")
    parser.add_argument("--no-normalize-coords", action="store_false", dest="normalize_coords")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_dir: pathlib.Path | None = None

    if args.stage in {"cua", "cua+author"}:
        if not args.start_url:
            raise SystemExit("--start-url is required when running the CUA stage")
        goal = args.goal or (
            "Starting from the site homepage, navigate to product detail pages (PDPs). "
            f"Collect at least {args.min_variant_pdp} PDP(s) with variants and "
            f"at least {args.min_variantless_pdp} PDP(s) without variants, "
            f"up to a maximum of {args.max_pdp} total PDPs. "
            "For each PDP, click the Add to Cart button, then call pdp_complete. "
            "For variant PDPs, click multiple variant options to capture their elements. "
            "When all PDPs are done, call finish."
        )
        model = GeminiCuaAdapter(
            model_name=args.cua_model,
            goal=goal,
            exclude_actions=args.exclude_action,
        )

        session = CuaSession(
            start_url=args.start_url,
            min_variantless_pdp=args.min_variantless_pdp,
            min_variant_pdp=args.min_variant_pdp,
            max_pdp=args.max_pdp,
            out_dir=out_dir,
            model_adapter=model,
            headless=args.headless,
            normalize_coords=args.normalize_coords,
            run_name=args.run_name,
            wait_load_state=args.wait_load_state,
            wait_timeout_ms=args.wait_timeout_ms,
            post_action_sleep=args.post_action_sleep,
        )
        run_dir = session.run()
        build_report_from_run(run_dir)

    if args.stage in {"author", "cua+author"}:
        target_run = pathlib.Path(args.run_dir) if args.run_dir else run_dir
        if not target_run:
            raise SystemExit("--run-dir is required for authoring without running CUA")
        generate_rules(target_run, model_name=args.author_model)
        build_report_from_run(target_run)

    if args.stage == "report":
        if not args.run_dir:
            raise SystemExit("--run-dir is required for report-only")
        build_report_from_run(pathlib.Path(args.run_dir))


if __name__ == "__main__":
    main()
