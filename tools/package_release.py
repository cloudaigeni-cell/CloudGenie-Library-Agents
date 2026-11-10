"""Package only source, tests, documentation, and a synthetic sample report."""

import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root.parent / "CloudGenie-Library-Agents-v1.zip"
allowed_roots = {"library_agents", "tests", "examples", "tools", "docs"}
allowed_top = {"README.md", "pyproject.toml", "config.example.json", "Dockerfile", ".dockerignore", ".gitignore", ".gitattributes"}
with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
    candidates = [root / name for name in allowed_top]
    for name in allowed_roots:
        candidates.extend((root / name).rglob("*"))
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if not path.is_file() or "__pycache__" in relative.parts:
            continue
        if relative.parts[0] not in allowed_roots and str(relative) not in allowed_top:
            continue
        if path.suffix in {".pyc", ".sqlite3"}:
            continue
        archive.write(path, Path("CloudGenie-Library-Agents") / relative)
print(destination)
