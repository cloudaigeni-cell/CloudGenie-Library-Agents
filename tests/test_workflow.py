import json
import os
import tempfile
import unittest
from pathlib import Path

from library_agents.agents import Coordinator, infer_year
from library_agents.cleanup import CleanupAgent, PURGE_CONFIRMATION, make_plan
from library_agents.extractors import document, photo
from library_agents.storage import digest, read_json, write_json

SETTINGS = {"workers": 3, "years": [], "extensions": [], "max_text_chars": 500_000, "max_similarity_items": 100, "photo_distance": 6, "topics": 0, "ocr": False, "llm_model": None}
TEXT = ("Storage backup recovery protects original data. Verify every original before removing duplicate copies.\n\n" * 3)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.run = self.base / "run"
        self.quarantine = self.base / "quarantine"
        (self.source / "2019").mkdir(parents=True)
        (self.source / "2024").mkdir()
        self.first = self.source / "2019" / "original.txt"
        self.second = self.source / "2024" / "copy.txt"
        self.first.write_text(TEXT, encoding="utf-8")
        self.second.write_text(TEXT, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def scan(self, **overrides):
        return Coordinator({**SETTINGS, **overrides}).run([self.source], self.run)

    def approve(self):
        path = self.base / "plan.json"
        plan = make_plan(self.run, path)
        for action in plan["actions"]:
            action["approved"] = True
        write_json(path, plan)
        return path, plan

    def test_year_workers_find_cross_year_duplicate(self):
        before = (digest(self.first), digest(self.second))
        summary = self.scan()
        self.assertEqual(summary["years"], {"2019": 1, "2024": 1})
        self.assertEqual(summary["exact_groups"], 1)
        self.assertEqual(len(summary["task_events"]), 2)
        self.assertEqual(before, (digest(self.first), digest(self.second)))

    def test_resume_reuses_cache(self):
        self.scan()
        summary = self.scan()
        self.assertEqual(summary["cached_files"], 2)
        self.assertEqual(summary["task_events"], [])

    def test_extension_and_year_filters_are_explicit(self):
        summary = self.scan(years=["2019"], extensions=[".txt"])
        self.assertEqual(summary["files"], 1)
        self.assertEqual(summary["excluded"], 1)
        self.assertEqual(summary["exact_groups"], 0)

    def test_same_photo_cloud_reference_is_export_repeat(self):
        for path in [self.first, self.second]:
            write_json(path.with_name(path.name + ".supplemental-metadata.json"), {"title": path.name, "url": "https://photos.google.com/photo/one-cloud-item", "photoTakenTime": {"timestamp": "1546300800"}})
        summary = self.scan()
        self.assertEqual(summary["export_repeat_groups"], 1)
        self.assertEqual(summary["exact_groups"], 0)
        plan = make_plan(self.run, self.base / "plan.json")
        self.assertEqual(plan["actions"], [])

    def test_takeout_year_overrides_filename(self):
        self.assertEqual(infer_year(self.first, {"photoTakenTime": {"timestamp": "1704067200"}}), ("2024", "takeout_photoTakenTime_UTC"))

    def test_camera_filename_year_is_recognized(self):
        self.assertEqual(infer_year(self.source / "IMG_20200102143000.jpg"), ("2020", "folder_or_filename_inference"))

    def test_plan_has_no_implicit_approval(self):
        self.scan()
        path = self.base / "plan.json"
        plan = make_plan(self.run, path)
        self.assertFalse(plan["actions"][0]["approved"])
        result = CleanupAgent().quarantine(self.run, path, self.quarantine, execute=True)
        self.assertEqual(result["quarantined"], 0)
        self.assertTrue(self.first.exists() and self.second.exists())

    def test_dry_run_leaves_every_source(self):
        self.scan()
        path, _ = self.approve()
        result = CleanupAgent().quarantine(self.run, path, self.quarantine)
        self.assertTrue(result["dry_run"])
        self.assertTrue(self.first.exists() and self.second.exists())
        self.assertFalse(self.quarantine.exists())

    def test_changed_keeper_blocks_cleanup(self):
        self.scan()
        path, plan = self.approve()
        Path(plan["actions"][0]["keeper_path"]).write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            CleanupAgent().quarantine(self.run, path, self.quarantine, True)
        self.assertTrue(self.second.exists())

    def test_changed_removal_blocks_cleanup(self):
        self.scan()
        path, plan = self.approve()
        Path(plan["actions"][0]["remove_path"]).write_text("different", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            CleanupAgent().quarantine(self.run, path, self.quarantine, True)
        self.assertTrue(self.first.exists() and self.second.exists())

    def test_path_tampering_is_rejected(self):
        self.scan()
        path, plan = self.approve()
        plan["actions"][0]["remove_path"] = str(self.base / "outside.txt")
        write_json(path, plan)
        with self.assertRaisesRegex(ValueError, "paths were edited"):
            CleanupAgent().quarantine(self.run, path, self.quarantine, True)

    def test_changed_catalog_invalidates_plan(self):
        self.scan()
        path, _ = self.approve()
        catalog = read_json(self.run / "catalog.json")
        catalog["created_utc"] = "edited"
        write_json(self.run / "catalog.json", catalog)
        with self.assertRaisesRegex(ValueError, "does not match"):
            CleanupAgent().quarantine(self.run, path, self.quarantine, True)

    def test_retained_copy_cannot_be_scheduled_for_removal(self):
        third = self.source / "2024" / "third.txt"
        third.write_text(TEXT, encoding="utf-8")
        self.scan()
        path, plan = self.approve()
        plan["actions"][1]["keeper_id"] = plan["actions"][0]["remove_id"]
        write_json(path, plan)
        with self.assertRaisesRegex(ValueError, "retained copy"):
            CleanupAgent().quarantine(self.run, path, self.quarantine, True)

    def test_quarantine_restore_and_resume(self):
        self.scan()
        path, plan = self.approve()
        agent = CleanupAgent()
        result = agent.quarantine(self.run, path, self.quarantine, True)
        self.assertEqual(result["quarantined"], 1)
        removed = Path(plan["actions"][0]["remove_path"])
        self.assertFalse(removed.exists())
        self.assertEqual(agent.quarantine(self.run, path, self.quarantine, True)["already_quarantined"], 1)
        self.assertEqual(agent.restore(self.run, self.quarantine)["restorable"], 1)
        self.assertEqual(agent.restore(self.run, self.quarantine, True)["restored"], 1)
        self.assertEqual(digest(self.first), digest(self.second))

    def test_purge_needs_second_approval_and_confirmation(self):
        self.scan()
        path, _ = self.approve()
        agent = CleanupAgent()
        agent.quarantine(self.run, path, self.quarantine, True)
        purge_path = self.base / "purge.json"
        plan = agent.purge_plan(self.run, self.quarantine, purge_path)
        self.assertFalse(plan["actions"][0]["approved"])
        plan["actions"][0]["approved"] = True
        write_json(purge_path, plan)
        with self.assertRaisesRegex(ValueError, "Permanent purge"):
            agent.purge(self.run, purge_path, self.quarantine, True)
        result = agent.purge(self.run, purge_path, self.quarantine, True, PURGE_CONFIRMATION)
        self.assertEqual(result["permanent_deletions"], 1)
        self.assertTrue(self.first.exists())

    def test_inside_source_output_and_quarantine_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "contain each other"):
            Coordinator(SETTINGS).run([self.source], self.source / "run")
        self.scan()
        path, _ = self.approve()
        with self.assertRaisesRegex(ValueError, "separate"):
            CleanupAgent().quarantine(self.run, path, self.source / "quarantine", True)

    def test_hardlinks_do_not_create_cleanup_actions(self):
        self.second.unlink()
        try:
            os.link(self.first, self.second)
        except OSError as error:
            self.skipTest(str(error))
        self.scan()
        self.assertEqual(make_plan(self.run, self.base / "plan.json")["actions"], [])

    def test_symlinks_are_not_traversed(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("do not scan", encoding="utf-8")
        link = self.source / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        summary = self.scan()
        self.assertEqual(summary["files"], 2)
        self.assertEqual(summary["discovery_errors"], 1)

    def test_truncated_text_is_not_same_text_evidence(self):
        self.scan(max_text_chars=100)
        self.assertEqual(read_json(self.run / "duplicates.json")["same_text"], [])

    def test_url_extraction_from_text(self):
        self.first.write_text("Reference https://example.com/storage and https://example.com/backup", encoding="utf-8")
        result = document(self.first)
        self.assertEqual(result["urls"], ["https://example.com/backup", "https://example.com/storage"])

    def test_legacy_document_is_explicitly_unsupported(self):
        self.assertEqual(document(self.source / "old.ppt")["status"], "unsupported_format")

    def test_office_readers_include_tables_and_notes(self):
        from docx import Document
        from pptx import Presentation
        from openpyxl import Workbook
        word = self.base / "guide.docx"
        doc = Document()
        doc.add_paragraph("Unique paragraph")
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "Table content"
        doc.save(word)
        contents = document(word)
        text = " ".join(unit["text"] for unit in contents["units"])
        self.assertEqual(text.count("Unique paragraph"), 1)
        self.assertIn("Table content", text)
        ppt = self.base / "guide.pptx"
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Storage overview"
        slide.notes_slide.notes_text_frame.text = "Speaker note evidence"
        deck.save(ppt)
        self.assertIn("Speaker note evidence", str(document(ppt)["units"]))
        xlsx = self.base / "book.xlsx"
        book = Workbook()
        book.active["A1"] = "=SUM(1,2)"
        book.save(xlsx)
        book.close()
        self.assertIn("=SUM(1,2)", str(document(xlsx)["units"]))

    def test_decoded_pixels_are_review_only(self):
        from PIL import Image, PngImagePlugin
        left, right = self.source / "2019" / "a.png", self.source / "2024" / "b.png"
        image = Image.new("RGB", (24, 24), "red")
        image.save(left)
        info = PngImagePlugin.PngInfo()
        info.add_text("comment", "valuable metadata")
        image.save(right, pnginfo=info)
        summary = self.scan()
        self.assertEqual(summary["decoded_pixel_groups"], 1)
        plan = make_plan(self.run, self.base / "plan.json")
        self.assertEqual(len(plan["actions"]), 1)  # Only the two identical TXT files.

    def test_exif_year_is_used_before_year_filter(self):
        from PIL import Image
        path = self.source / "capture.jpg"
        image = Image.new("RGB", (24, 24), "blue")
        exif = Image.Exif()
        exif[36867] = "2020:06:07 12:00:00"
        image.save(path, exif=exif)
        summary = self.scan(years=["2020"])
        self.assertEqual(summary["files"], 1)
        self.assertEqual(summary["years"], {"2020": 1})

    def test_ocr_text_can_enter_a_topic_pack_with_provenance(self):
        from library_agents.analysis import ConsolidationAgent
        row = {"id": "image-1", "name": "reading.png", "path": str(self.first), "sha256": "test-hash", "photo": {"ocr_text": TEXT}}
        topics = {"groups": [{"id": "topic-001", "keywords": ["storage"], "members": ["image-1"]}]}
        paths = ConsolidationAgent().run([row], topics, self.base / "packs", SETTINGS)
        self.assertIn("unverified image OCR", Path(paths[0]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
