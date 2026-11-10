"""Shared persistence and filesystem checks used by analysis and cleanup."""

import csv
import hashlib
import json
import os
from pathlib import Path


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_csv(path, rows, fields):
    def cell(value):
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=True)
        value = "" if value is None else str(value)
        return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value

    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key)) for key in fields})


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def signature(path):
    stat = Path(path).stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino]


def is_link(path):
    path = Path(path)
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def checked_file(path, roots):
    path = Path(path).absolute()
    candidates = [Path(root).resolve() for root in roots if inside(path, root)]
    if not candidates:
        raise ValueError("File is outside approved source roots: " + str(path))
    root = max(candidates, key=lambda value: len(value.parts))
    for parent in [path, *path.parents]:
        if is_link(parent):
            raise ValueError("Symlink or junction is not allowed: " + str(parent))
        if parent == root:
            break
    if not path.is_file():
        raise ValueError("Source file is missing: " + str(path))
    return path


def append_event(path, value):
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
