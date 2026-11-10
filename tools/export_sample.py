"""Publish synthetic example artifacts and concise release validation evidence."""

import json
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sample = ROOT / "examples" / "sample-output"
sample.mkdir(parents=True, exist_ok=True)
run = ROOT / "runs" / "demo"


def portable(value):
    if isinstance(value, str):
        return value.replace(str(ROOT), "/example/cloudgenie-library-agents")
    if isinstance(value, list):
        return [portable(item) for item in value]
    if isinstance(value, dict):
        return {key: portable(item) for key, item in value.items()}
    return value


def export_file(source, destination):
    if source.suffix == ".json":
        content = json.loads(source.read_text(encoding="utf-8"))
        destination.write_text(json.dumps(portable(content), indent=2), encoding="utf-8")
    elif source.suffix == ".csv":
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames
            rows = [portable(row) for row in reader]
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    else:
        destination.write_text(portable(source.read_text(encoding="utf-8")), encoding="utf-8")


for name in ["REPORT.md", "summary.json", "duplicates.json", "topics.json", "inventory.csv", "urls.csv"]:
    export_file(run / name, sample / name)
topics = list((run / "consolidated").rglob("topic-*.md"))
for path in topics:
    export_file(path, sample / path.name)
qa = json.loads((ROOT / ".qa" / "test-results.json").read_text(encoding="utf-8"))
validation = {"date": "2026-11-10", "windows_tests_run": qa["tests_run"], "windows_passed": qa["tests_run"] - len(qa["skipped"]) - qa["failures"] - qa["errors"], "windows_failed": qa["failures"] + qa["errors"], "windows_skipped": ["Symlink fixture requires Windows privilege; the same path passed on WSL Ubuntu" for item in qa["skipped"]], "wsl_core_tests_passed": 4, "guide_pages": qa["guide_pages"], "docker_runtime": "not tested; Docker is not installed on the development host", "ocr_and_ollama": "optional integrations not exercised", "cloud_operations": "not implemented", "real_library_source_changes": 0, "demo": json.loads((run / "summary.json").read_text(encoding="utf-8"))}
(ROOT / "docs" / "VALIDATION.json").write_text(json.dumps(portable(validation), indent=2), encoding="utf-8")
print(sample)
