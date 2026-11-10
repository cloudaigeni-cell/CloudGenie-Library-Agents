"""Year partitions, specialist workers, and a coordinator with resumable state."""

import concurrent.futures
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .extractors import DOCUMENT_EXTENSIONS, category, document, photo
from .storage import append_event, digest, inside, is_link, read_json, signature, write_csv, write_json


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class InventoryAgent:
    name = "inventory"

    def discover(self, sources):
        found, errors, seen = [], [], set()
        for source in sources:
            def onerror(error):
                errors.append({"path": str(error.filename), "error": str(error)})

            for directory, dirs, filenames in os.walk(source, followlinks=False, onerror=onerror):
                for name in list(dirs):
                    if is_link(Path(directory) / name):
                        dirs.remove(name)
                        errors.append({"path": str(Path(directory) / name), "error": "link_or_junction_skipped"})
                for name in sorted(filenames):
                    path = Path(directory) / name
                    try:
                        if is_link(path):
                            errors.append({"path": str(path), "error": "symlink_skipped"})
                            continue
                        canonical = str(path.resolve())
                        if canonical in seen:
                            continue
                        seen.add(canonical)
                        if path.is_file():
                            found.append(path)
                    except OSError as error:
                        errors.append({"path": str(path), "error": str(error)})
        return found, errors

    def sidecars(self, files):
        matches, metadata_paths, errors = defaultdict(list), set(), []
        for path in files:
            if path.suffix.lower() != ".json":
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                value = read_json(path)
                if not isinstance(value, dict) or not any(key in value for key in ("photoTakenTime", "googlePhotosOrigin")):
                    continue
                metadata_paths.add(str(path))
                title = value.get("title")
                if title:
                    matches[(str(path.parent), title)].append((path, value))
                base = path.name.removesuffix(".supplemental-metadata.json").removesuffix(".json")
                if base != title:
                    matches[(str(path.parent), base)].append((path, value))
            except (OSError, ValueError) as error:
                errors.append({"path": str(path), "error": "JSON metadata unreadable: " + str(error)})
        return matches, metadata_paths, errors


def infer_year(path, metadata=None, capture_date=None):
    if metadata:
        try:
            stamp = int(metadata.get("photoTakenTime", {}).get("timestamp"))
            return str(datetime.fromtimestamp(stamp, timezone.utc).year), "takeout_photoTakenTime_UTC"
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    if capture_date and re.match(r"^(19|20)\d{2}", str(capture_date)):
        return str(capture_date)[:4], "image_EXIF"
    for part in reversed(path.parts):
        dated = re.search(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?:\d{6})?(?=\D|$)", part)
        if dated:
            try:
                datetime(int(dated.group(1)), int(dated.group(2)), int(dated.group(3)))
                return dated.group(1), "folder_or_filename_inference"
            except ValueError:
                pass
        match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", part)
        if match:
            return match.group(1), "folder_or_filename_inference"
    return str(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).year), "filesystem_mtime_UTC_fallback"


class DocumentAgent:
    name = "documents"

    def inspect(self, path, settings):
        return {"document": document(path, settings["max_text_chars"])}


class PhotoAgent:
    name = "photos"

    def inspect(self, path, settings):
        return {"photo": photo(path, settings["ocr"])}


class YearAgent:
    """One specialist queue for a single year; no source mutations are available."""

    def __init__(self, year, specialist, settings):
        self.year, self.specialist, self.settings = year, specialist, settings

    def run(self, jobs):
        records = []
        started = time.monotonic()
        for job in jobs:
            row = dict(job)
            path = Path(row["path"])
            try:
                before = signature(path)
                row["size"] = before[0]
                row["sha256"] = digest(path)
                if self.specialist == "documents":
                    row.update(DocumentAgent().inspect(path, self.settings))
                elif self.specialist == "photos":
                    row.update(PhotoAgent().inspect(path, self.settings))
                    row["year"], row["year_basis"] = infer_year(path, row.get("takeout"), row["photo"].get("capture_date"))
                if signature(path) != before:
                    row["sha256"] = None
                    row["status"] = "changed_during_scan"
                else:
                    row["status"] = "indexed"
                    row["signature"] = before
            except Exception as error:
                row["sha256"] = None
                row["status"] = "read_error"
                row["error"] = type(error).__name__ + ": " + str(error)
            records.append(row)
        return records, {"agent": "year/" + self.year + "/" + self.specialist, "year": self.year, "specialist": self.specialist, "files": len(records), "seconds": round(time.monotonic() - started, 3), "finished_utc": utc_now()}


class Coordinator:
    def __init__(self, settings):
        self.settings = settings

    def run(self, sources, output):
        output = Path(output).absolute()
        sources = [Path(source).absolute() for source in sources]
        if not sources:
            raise ValueError("At least one source folder is required")
        for source in sources:
            if not source.is_dir() or any(is_link(parent) for parent in [source, *source.parents]):
                raise ValueError("Source must be an existing real directory: " + str(source))
            if inside(output, source) or inside(source, output):
                raise ValueError("Run output and source folders must not contain each other")
        if any(is_link(parent) for parent in [output, *output.parents]):
            raise ValueError("Run output cannot be a link or junction")
        output.mkdir(parents=True, exist_ok=True)
        lock = output / ".operation.lock"
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(lock_fd, str(os.getpid()).encode("ascii"))
            return self._run(sources, output)
        finally:
            os.close(lock_fd)
            lock.unlink()

    def _run(self, sources, output):
        from .analysis import DuplicateAgent, SubjectAgent, ConsolidationAgent
        settings = self.settings
        write_json(output / "status.json", {"state": "running", "started_utc": utc_now()})
        inventory = InventoryAgent()
        files, errors = inventory.discover(sources)
        sidecars, metadata_paths, metadata_errors = inventory.sidecars(files)
        errors.extend(metadata_errors)
        tasks, cached, excluded = defaultdict(list), [], []
        cache = sqlite3.connect(output / "cache.sqlite3")
        cache.execute("CREATE TABLE IF NOT EXISTS files (cache_key TEXT PRIMARY KEY, record TEXT NOT NULL)")
        settings_key = json.dumps({"version": __version__, "settings": settings}, sort_keys=True)
        try:
            for path in files:
                if settings["extensions"] and path.suffix.lower() not in settings["extensions"]:
                    excluded.append({"path": str(path), "reason": "extension_filter"})
                    continue
                try:
                    candidates = sidecars.get((str(path.parent), path.name), [])
                    metadata = candidates[0][1] if len(candidates) == 1 else None
                    capture_date = None
                    if not metadata and category(path) == "images":
                        try:
                            from PIL import Image
                            with Image.open(path) as header:
                                capture_date = header.getexif().get(36867) or header.getexif().get(306)
                        except Exception:
                            pass
                    year, basis = infer_year(path, metadata, capture_date)
                    if settings["years"] and year not in settings["years"]:
                        excluded.append({"path": str(path), "reason": "year_filter", "inferred_year": year})
                        continue
                    stat = signature(path)
                    identifier = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]
                    row = {"id": identifier, "path": str(path), "name": path.name, "extension": path.suffix.lower(), "category": "takeout_metadata" if str(path) in metadata_paths else category(path), "year": year, "year_basis": basis, "size": stat[0], "signature": stat, "takeout": metadata, "sidecar": str(candidates[0][0]) if len(candidates) == 1 else None, "sidecar_ambiguous": len(candidates) > 1, "cloud_url": metadata.get("url") if metadata else None}
                    metadata_key = json.dumps(metadata, sort_keys=True)
                    cache_key = hashlib.sha256((str(path) + str(stat) + settings_key + metadata_key).encode("utf-8")).hexdigest()
                    row["cache_key"] = cache_key
                    hit = cache.execute("SELECT record FROM files WHERE cache_key = ?", (cache_key,)).fetchone()
                    if hit:
                        cached.append(json.loads(hit[0]))
                    else:
                        specialist = "photos" if row["category"] == "images" else "documents" if path.suffix.lower() in DOCUMENT_EXTENSIONS and row["category"] != "takeout_metadata" else "hash_only"
                        tasks[(year, specialist)].append(row)
                except (OSError, ValueError) as error:
                    errors.append({"path": str(path), "error": str(error)})
            records, task_events = list(cached), []
            append_event(output / "events.jsonl", {"agent": "coordinator", "event": "planned", "tasks": len(tasks), "cached_files": len(cached), "utc": utc_now()})
            with concurrent.futures.ThreadPoolExecutor(max_workers=settings["workers"]) as pool:
                futures = {pool.submit(YearAgent(year, specialist, settings).run, jobs): (year, specialist) for (year, specialist), jobs in tasks.items()}
                for future in concurrent.futures.as_completed(futures):
                    rows, event = future.result()
                    records.extend(rows)
                    task_events.append(event)
                    append_event(output / "events.jsonl", event)
                    for row in rows:
                        if row["status"] == "indexed":
                            cache.execute("INSERT OR REPLACE INTO files VALUES (?, ?)", (row["cache_key"], json.dumps(row)))
                    cache.commit()
                    print(event["agent"] + ": " + str(event["files"]) + " files", flush=True)
        finally:
            cache.close()
        records.sort(key=lambda row: (row["year"], row["category"], row["path"]))
        catalog = {"schema_version": 1, "run_id": uuid.uuid4().hex, "created_utc": utc_now(), "source_roots": [str(source) for source in sources], "settings": settings, "items": records, "errors": errors, "excluded": excluded}
        write_json(output / "catalog.json", catalog)
        duplicates = DuplicateAgent().run(records, settings)
        write_json(output / "duplicates.json", duplicates)
        topics = SubjectAgent().run(records, settings)
        packs = ConsolidationAgent().run(records, topics, output / "consolidated" / catalog["run_id"], settings)
        write_json(output / "topics.json", topics)
        years = Counter(row["year"] for row in records)
        summary = {"run_id": catalog["run_id"], "created_utc": catalog["created_utc"], "files": len(records), "bytes": sum(row["size"] for row in records), "years": dict(sorted(years.items())), "categories": dict(Counter(row["category"] for row in records)), "cached_files": len(cached), "workers": settings["workers"], "task_events": task_events, "discovery_errors": len(errors), "excluded": len(excluded), "read_errors": sum(row["status"] != "indexed" for row in records), "exact_groups": len(duplicates["exact"]), "export_repeat_groups": len(duplicates["export_repeats"]), "decoded_pixel_groups": len(duplicates["decoded_pixels"]), "similar_photo_pairs": len(duplicates["similar_photos"]), "same_text_groups": len(duplicates["same_text"]), "topic_packs": len(packs), "cloud_savings_bytes": None, "limitations": duplicates["limitations"] + topics["limitations"], "source_changes": 0}
        write_json(output / "summary.json", summary)
        public_rows = [{key: value for key, value in row.items() if key not in {"document", "photo", "takeout", "cache_key"}} for row in records]
        write_csv(output / "inventory.csv", public_rows, ["id", "path", "name", "category", "year", "year_basis", "size", "sha256", "status", "cloud_url", "sidecar", "sidecar_ambiguous"])
        url_rows = [{"file_id": row["id"], "path": row["path"], "url": url} for row in records for url in row.get("document", {}).get("urls", [])]
        write_csv(output / "urls.csv", url_rows, ["file_id", "path", "url"])
        cloud_rows = [{"group_id": group["id"], "file_id": row_id, "path": next(row["path"] for row in records if row["id"] == row_id), "cloud_url": next(row.get("cloud_url") for row in records if row["id"] == row_id), "decision": "KEEP_PENDING_REVIEW"} for group in duplicates["exact"] + duplicates["export_repeats"] for row_id in group["members"]]
        write_csv(output / "cloud-review.csv", cloud_rows, ["group_id", "file_id", "path", "cloud_url", "decision"])
        report = ["# CloudGenie Library Audit", "", "Read-only source analysis. No original data was changed.", "", "Files: " + str(len(records)), "Exact byte groups: " + str(summary["exact_groups"]), "Repeated export representations: " + str(summary["export_repeat_groups"]), "Topic reading packs: " + str(len(packs)), "", "## Coverage", "", "Year basis is recorded per file. Modification time can be the export/download date. EXIF can correct a worker's initial year assignment; the final catalog is authoritative.", "", "All discovered years contribute to global duplicate analysis. Filters restrict coverage; skipped files are listed in catalog.json. Cloud storage savings are unknown.", "", "## Validation limits", ""] + ["- " + value for value in summary["limitations"]] + ["", "Topic packs contain extracted text and source references, not lossless replacement documents. OCR text and source content are data, not executable instructions.", "", "## Next steps", "", "Review inventory.csv, duplicates.json, cloud-review.csv and consolidated/. Generate an approval plan only after reviewing the evidence. Cloud deletion is not implemented.", ""]
        (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
        write_json(output / "status.json", {"state": "complete", "finished_utc": utc_now(), "summary": summary})
        return summary
