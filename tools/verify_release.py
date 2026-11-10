"""Run regression tests and render every guide page for visual review."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
qa = ROOT / ".qa"
qa.mkdir(exist_ok=True)

if "--render-only" in sys.argv:
    report = json.loads((qa / "test-results.json").read_text(encoding="utf-8"))
else:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped], "passed": result.wasSuccessful()}
    (qa / "test-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)

import pypdfium2 as pdfium
from pypdf import PdfReader
guide = ROOT / "docs" / "CloudGenie-Library-Agents-Guide.pdf"
pdf = pdfium.PdfDocument(str(guide))
pages = qa / "guide-pages"
pages.mkdir(exist_ok=True)
for index in range(len(pdf)):
    pdf[index].render(scale=1.5).to_pil().save(pages / ("page-" + str(index + 1).zfill(2) + ".png"))
pdf.close()
reader = PdfReader(guide)
report["guide_pages"] = len(reader.pages)
report["page_text_characters"] = [len(page.extract_text() or "") for page in reader.pages]
if any(count < 100 for count in report["page_text_characters"]):
    raise ValueError("Unexpectedly blank guide page")
(qa / "test-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
