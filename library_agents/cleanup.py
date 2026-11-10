"""Approval-gated local cleanup. No cloud credentials or browser deletion hooks."""

import contextlib
import json
import os
from pathlib import Path

from .storage import append_event, checked_file, digest, inside, is_link, read_json, signature, write_json

PURGE_CONFIRMATION = "PERMANENTLY_DELETE_APPROVED_QUARANTINE"


@contextlib.contextmanager
def operation_lock(run):
    lock = Path(run) / ".operation.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        lock.unlink()


def load_catalog(run):
    path = Path(run) / "catalog.json"
    catalog = read_json(path)
    if catalog.get("schema_version") != 1:
        raise ValueError("Unsupported catalog schema")
    index = {row["id"]: row for row in catalog["items"]}
    if len(index) != len(catalog["items"]):
        raise ValueError("Catalog has repeated item IDs")
    return catalog, index, digest(path)


def make_plan(run, destination):
    catalog, index, catalog_hash = load_catalog(run)
    duplicates = read_json(Path(run) / "duplicates.json")
    actions = []
    for group in duplicates["exact"]:
        members = sorted((index[key] for key in group["members"]), key=lambda row: (row["year"], row["path"]))
        keeper = members[0]
        for row in members[1:]:
            if row["signature"][3:] == keeper["signature"][3:]:
                continue
            actions.append({"group_id": group["id"], "keeper_id": keeper["id"], "remove_id": row["id"], "sha256": group["sha256"], "size": row["size"], "keeper_path": keeper["path"], "remove_path": row["path"], "approved": False})
    plan = {"schema_version": 1, "kind": "quarantine", "run_id": catalog["run_id"], "catalog_sha256": catalog_hash, "cloud_effect": "none; this plan only affects local files", "actions": actions}
    if Path(destination).exists():
        raise ValueError("Refusing to overwrite an existing review plan")
    write_json(destination, plan)
    return plan


def validate_plan(run, plan_path, kind):
    catalog, index, catalog_hash = load_catalog(run)
    plan = read_json(plan_path)
    if plan.get("schema_version") != 1 or plan.get("kind") != kind:
        raise ValueError("Wrong plan type or schema")
    if plan.get("catalog_sha256") != catalog_hash or plan.get("run_id") != catalog["run_id"]:
        raise ValueError("Plan does not match this catalog; regenerate and review it")
    approved = [row for row in plan["actions"] if row.get("approved") is True]
    removals = [row["remove_id"] for row in approved]
    if len(removals) != len(set(removals)):
        raise ValueError("Repeated removal in approval plan")
    if set(removals) & {row["keeper_id"] for row in approved}:
        raise ValueError("A retained copy is also scheduled for removal")
    for action in approved:
        source, keeper = index[action["remove_id"]], index[action["keeper_id"]]
        if source["id"] == keeper["id"]:
            raise ValueError("A file cannot be its own retained copy")
        if not source.get("sha256") or source["sha256"] != keeper.get("sha256") or source["sha256"] != action["sha256"]:
            raise ValueError("Approved files do not have matching full-byte evidence")
        if source["size"] != keeper["size"] or source["size"] != action["size"]:
            raise ValueError("Size mismatch in approval plan")
        if source["category"] == "takeout_metadata" or keeper["category"] == "takeout_metadata":
            raise ValueError("Metadata sidecars cannot be cleaned up by this plan")
        # The displayed paths are review aids. Execution always uses the bound catalog IDs.
        if action.get("remove_path") != source["path"] or action.get("keeper_path") != keeper["path"]:
            raise ValueError("Approval paths were edited; regenerate the plan")
    return catalog, index, approved, catalog_hash


def quarantine_root(run, catalog, quarantine):
    root = Path(quarantine).absolute()
    for parent in [root, *root.parents]:
        if is_link(parent):
            raise ValueError("Quarantine path contains a link or junction")
    for source in catalog["source_roots"] + [str(Path(run).absolute())]:
        if inside(root, source) or inside(source, root):
            raise ValueError("Quarantine, sources and run folder must be separate")
    root = root / catalog["run_id"]
    if is_link(root):
        raise ValueError("Quarantine run directory cannot be a link or junction")
    return root


def backup_path(root, row):
    return root / (row["id"] + "__" + Path(row["path"]).name[-160:])


def verify_original(row, roots):
    path = checked_file(row["path"], roots)
    before = signature(path)
    if digest(path) != row["sha256"] or before != signature(path):
        raise ValueError("File changed or differs from the scan: " + str(path))
    return path


def copy_verified(source, destination, expected_hash):
    destination = Path(destination)
    if destination.exists() or is_link(destination):
        raise ValueError("Destination already exists: " + str(destination))
    before = signature(source)
    created = False
    try:
        with Path(source).open("rb") as incoming, destination.open("xb") as outgoing:
            created = True
            for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if digest(destination) != expected_hash or signature(source) != before:
            raise ValueError("Copy failed verification or source changed")
    except Exception:
        # This path was created exclusively by this operation, never a pre-existing file.
        if created and destination.exists():
            destination.unlink()
        raise


def journal_entries(root):
    journal = root / "journal.jsonl"
    if not journal.exists():
        return []
    with journal.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class CleanupAgent:
    name = "cleanup"

    def quarantine(self, run, plan_path, quarantine, execute=False):
        with operation_lock(run):
            catalog, index, actions, catalog_hash = validate_plan(run, plan_path, "quarantine")
            root = quarantine_root(run, catalog, quarantine)
            roots = catalog["source_roots"]
            operations = []
            # Complete preflight before changing any source. Every retained original is rehashed.
            for action in actions:
                row, keeper = index[action["remove_id"]], index[action["keeper_id"]]
                kept_path = verify_original(keeper, roots)
                source = Path(row["path"])
                backup = backup_path(root, row)
                if backup.exists() and (is_link(backup) or digest(backup) != row["sha256"]):
                    raise ValueError("Existing backup is not the expected original")
                if source.exists():
                    source = verify_original(row, roots)
                    if os.path.samefile(source, kept_path):
                        raise ValueError("Hardlink aliases do not represent reclaimable duplicate copies")
                    operations.append((action, row, keeper, source, backup, False))
                elif backup.exists():
                    operations.append((action, row, keeper, source, backup, True))
                else:
                    raise ValueError("Both original and quarantine copy are missing")
            if not execute:
                return {"dry_run": True, "approved": len(operations), "quarantine": str(root), "source_changes": 0}
            root.mkdir(parents=True, exist_ok=True)
            completed = 0
            for action, row, keeper, source, backup, recovered in operations:
                verify_original(keeper, roots)
                event = {"event": "prepared", "item_id": row["id"], "keeper_id": keeper["id"], "sha256": row["sha256"], "catalog_sha256": catalog_hash, "source": str(source), "backup": str(backup)}
                append_event(root / "journal.jsonl", event)
                if not recovered:
                    if not backup.exists():
                        copy_verified(source, backup, row["sha256"])
                    verify_original(row, roots)
                    verify_original(keeper, roots)
                    source.unlink()
                    completed += 1
                event["event"] = "quarantined"
                append_event(root / "journal.jsonl", event)
            return {"dry_run": False, "quarantined": completed, "already_quarantined": len(operations) - completed, "journal": str(root / "journal.jsonl"), "cloud_changes": 0}

    def restore(self, run, quarantine, execute=False):
        with operation_lock(run):
            catalog, index, catalog_hash = load_catalog(run)
            root = quarantine_root(run, catalog, quarantine)
            entries = {entry["item_id"]: entry for entry in journal_entries(root) if entry.get("catalog_sha256") == catalog_hash}
            operations = []
            for key, entry in entries.items():
                if entry["event"] == "purged":
                    continue
                row = index[key]
                backup = backup_path(root, row)
                if not backup.exists():
                    raise ValueError("Quarantine backup is missing: " + str(backup))
                if is_link(backup) or digest(backup) != row["sha256"]:
                    raise ValueError("Backup verification failed")
                source = Path(row["path"])
                if not any(inside(source, approved_root) for approved_root in catalog["source_roots"]):
                    raise ValueError("Restore target is outside catalog roots")
                if any(is_link(parent) for parent in [source, *source.parents]):
                    raise ValueError("Restore target contains a link")
                if source.exists():
                    verify_original(row, catalog["source_roots"])
                    continue
                operations.append((row, backup, source, entry))
            if not execute:
                return {"dry_run": True, "restorable": len(operations)}
            for row, backup, source, entry in operations:
                source.parent.mkdir(parents=True, exist_ok=True)
                copy_verified(backup, source, row["sha256"])
                append_event(root / "journal.jsonl", {**entry, "event": "restored"})
            return {"dry_run": False, "restored": len(operations), "backups_retained": True}

    def purge_plan(self, run, quarantine, destination):
        catalog, index, catalog_hash = load_catalog(run)
        root = quarantine_root(run, catalog, quarantine)
        entries = {entry["item_id"]: entry for entry in journal_entries(root) if entry.get("catalog_sha256") == catalog_hash}
        actions = []
        for key, event in entries.items():
            if event["event"] != "quarantined":
                continue
            row, keeper = index[key], index[event["keeper_id"]]
            actions.append({"remove_id": key, "keeper_id": keeper["id"], "remove_path": row["path"], "keeper_path": keeper["path"], "sha256": row["sha256"], "size": row["size"], "approved": False})
        if Path(destination).exists():
            raise ValueError("Refusing to overwrite an existing purge review plan")
        plan = {"schema_version": 1, "kind": "purge", "run_id": catalog["run_id"], "catalog_sha256": catalog_hash, "actions": actions}
        write_json(destination, plan)
        return plan

    def purge(self, run, plan_path, quarantine, execute=False, confirmation=""):
        with operation_lock(run):
            catalog, index, actions, catalog_hash = validate_plan(run, plan_path, "purge")
            root = quarantine_root(run, catalog, quarantine)
            events = {entry["item_id"]: entry for entry in journal_entries(root) if entry.get("catalog_sha256") == catalog_hash}
            operations = []
            for action in actions:
                row, keeper = index[action["remove_id"]], index[action["keeper_id"]]
                if events.get(row["id"], {}).get("event") != "quarantined":
                    raise ValueError("Purge is limited to journaled quarantined copies")
                verify_original(keeper, catalog["source_roots"])
                backup = backup_path(root, row)
                if not backup.is_file() or is_link(backup) or digest(backup) != row["sha256"]:
                    raise ValueError("Quarantine file failed validation")
                operations.append((row, keeper, backup))
            if not execute:
                return {"dry_run": True, "approved": len(operations), "permanent_deletions": 0}
            if confirmation != PURGE_CONFIRMATION:
                raise ValueError("Permanent purge requires --confirm " + PURGE_CONFIRMATION)
            for row, keeper, backup in operations:
                verify_original(keeper, catalog["source_roots"])
                if digest(backup) != row["sha256"]:
                    raise ValueError("Backup changed before purge")
                backup.unlink()
                append_event(root / "journal.jsonl", {"event": "purged", "item_id": row["id"], "keeper_id": keeper["id"], "sha256": row["sha256"], "catalog_sha256": catalog_hash})
            return {"dry_run": False, "permanent_deletions": len(operations), "cloud_changes": 0}
