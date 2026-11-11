"""Offline, explicitly invoked human QA CLI (not an agent approval bypass)."""
import argparse
import json
from core import Engine, Refusal


def main():
    parser = argparse.ArgumentParser(description="RowVerdict local CSV QA. Agent exports must use the Hermes tool/approval gate.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--root", action="append", default=[])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect"); p.add_argument("source"); p.add_argument("--delimiter", default=",")
    p = sub.add_parser("plan"); p.add_argument("source"); p.add_argument("contract")
    p = sub.add_parser("history"); p.add_argument("--plan-id")
    p = sub.add_parser("export"); p.add_argument("plan_id"); p.add_argument("--reviewed-plan", required=True, help="Repeat exact plan ID after human review; never use to bypass a denied Hermes call")
    args = parser.parse_args()
    app = Engine(args.data_dir, args.root)
    try:
        if args.command == "inspect":
            result = app.inspect(args.source, args.delimiter)
        elif args.command == "plan":
            with open(args.contract, encoding="utf-8") as f:
                result = app.plan(args.source, json.load(f))
        elif args.command == "history":
            result = app.get(args.plan_id) if args.plan_id else app.history()
        else:
            if args.reviewed_plan != args.plan_id:
                raise Refusal("REVIEW: reviewed plan ID must match the export plan ID")
            result = app.export(args.plan_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (Refusal, OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error) if isinstance(error, Refusal) else "INPUT_OR_STATE: check paths and arguments"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
