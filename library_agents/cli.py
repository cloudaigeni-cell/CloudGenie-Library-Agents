import argparse
import importlib.util
import json
import sys
from pathlib import Path

from .agents import Coordinator
from .cleanup import CleanupAgent, make_plan
from .storage import read_json


def parser():
    root = argparse.ArgumentParser(description="CloudGenie Library Agents: inventory, compare, consolidate, review, then clean up")
    commands = root.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="Read-only scan with year and format specialists")
    scan.add_argument("--config", type=Path)
    scan.add_argument("--source", action="append", type=Path)
    scan.add_argument("--output", type=Path)
    scan.add_argument("--workers", type=int)
    scan.add_argument("--year", action="append")
    scan.add_argument("--extensions", help="Comma-separated extensions, e.g. pdf,pptx,jpg")
    scan.add_argument("--max-text-chars", type=int)
    scan.add_argument("--max-similarity-items", type=int)
    scan.add_argument("--photo-distance", type=int)
    scan.add_argument("--topics", type=int)
    scan.add_argument("--ocr", action="store_true", default=None)
    scan.add_argument("--llm-model", help="Opt-in Ollama model at 127.0.0.1:11434; source text is sent to that local service")
    commands.add_parser("doctor", help="Check optional analysis packages")
    plan = commands.add_parser("plan", help="Create an unapproved exact-byte local quarantine plan")
    plan.add_argument("--run", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    for name in ["apply", "restore", "purge-plan", "purge"]:
        command = commands.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--quarantine", type=Path, required=True)
        if name in {"apply", "purge"}:
            command.add_argument("--plan", type=Path, required=True)
        if name == "purge-plan":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--execute", action="store_true", help="Actually perform the reviewed action; otherwise dry-run")
        if name == "purge":
            command.add_argument("--confirm", default="")
    return root


def scan_options(args):
    config = read_json(args.config) if args.config else {}
    defaults = {"workers": 4, "years": [], "extensions": [], "max_text_chars": 500_000, "max_similarity_items": 10_000, "photo_distance": 6, "topics": 0, "ocr": False, "llm_model": None}
    unknown = set(config) - set(defaults) - {"sources", "output"}
    if unknown:
        raise ValueError("Unknown config settings: " + ", ".join(sorted(unknown)))
    options = {**defaults, **{key: value for key, value in config.items() if key in defaults}}
    for key in defaults:
        arg_name = "year" if key == "years" else key
        value = getattr(args, arg_name, None)
        if value is not None:
            options[key] = value
    extensions = options["extensions"]
    if isinstance(extensions, str):
        extensions = extensions.split(",")
    options["extensions"] = sorted({"." + value.strip().lstrip(".").lower() for value in extensions if value.strip()})
    options["years"] = [str(value) for value in options["years"]]
    if any(not year.isdigit() or not 1900 <= int(year) <= 2100 for year in options["years"]):
        raise ValueError("Years must be between 1900 and 2100")
    if not 1 <= options["workers"] <= 32 or options["max_text_chars"] < 100 or options["max_similarity_items"] < 1 or not 0 <= options["photo_distance"] <= 64 or options["topics"] < 0:
        raise ValueError("Invalid worker count, extraction limit, similarity limit or topic setting")
    sources = args.source or [Path(value) for value in config.get("sources", [])]
    output = args.output or config.get("output")
    if not sources or not output:
        raise ValueError("Provide --source and --output, or sources and output in --config")
    return sources, Path(output), options


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        agent = CleanupAgent()
        if args.command == "doctor":
            packages = {name: importlib.util.find_spec(name) is not None for name in ["PIL", "imagehash", "pypdf", "docx", "pptx", "openpyxl", "sklearn", "pytesseract"]}
            result = {"python": sys.version.split()[0], "packages": packages, "core": "stdlib inventory, complete byte hashing and cleanup available", "cloud_deletion": "not implemented"}
        elif args.command == "scan":
            sources, output, options = scan_options(args)
            result = Coordinator(options).run(sources, output)
        elif args.command == "plan":
            result = make_plan(args.run, args.output)
        elif args.command == "apply":
            result = agent.quarantine(args.run, args.plan, args.quarantine, args.execute)
        elif args.command == "restore":
            result = agent.restore(args.run, args.quarantine, args.execute)
        elif args.command == "purge-plan":
            result = agent.purge_plan(args.run, args.quarantine, args.output)
        else:
            result = agent.purge(args.run, args.plan, args.quarantine, args.execute, args.confirm)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
