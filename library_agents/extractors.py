"""Format readers. Extracted text is evidence, never permission to delete a file."""

import hashlib
import re
import warnings
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif"}
TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".html", ".htm", ".json", ".xml", ".py", ".sh", ".yaml", ".yml"}
DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls", ".odt", ".odp", ".ods"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".3gp"}
URL_PATTERN = re.compile(r"(?:https?|ftp)://[^\s<>\"'\x00-\x1f]+", re.I)


def category(path):
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "images"
    if ext in VIDEO_EXTENSIONS:
        return "videos"
    if ext == ".pdf":
        return "pdfs"
    if ext in {".ppt", ".pptx", ".odp"}:
        return "presentations"
    if ext in {".doc", ".docx", ".odt"}:
        return "word_documents"
    if ext in {".xls", ".xlsx", ".ods", ".csv", ".tsv"}:
        return "spreadsheets"
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in {".zip", ".gz", ".tgz", ".7z", ".rar"}:
        return "archives"
    return "other"


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        for key, value in attrs:
            if key in {"href", "src"} and value:
                self.links.append(value)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def document(path, max_chars=500_000):
    path = Path(path)
    ext = path.suffix.lower()
    units, urls, notes = [], set(), []
    used, truncated = 0, False

    def add(label, text):
        nonlocal used, truncated
        text = str(text or "").strip()
        if not text:
            return True
        available = max_chars - used
        if len(text) > available:
            text = text[:max(0, available)]
            truncated = True
        if text:
            units.append({"label": label, "text": text})
            urls.update(URL_PATTERN.findall(text))
            used += len(text)
        return used < max_chars

    try:
        if ext in TEXT_EXTENSIONS:
            with path.open("rb") as handle:
                data = handle.read(max_chars * 4 + 4)
            truncated = len(data) > max_chars * 4
            if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                text = data.decode("utf-16", errors="replace")
            else:
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = data.decode("cp1252", errors="replace")
                    notes.append("Text decoded as cp1252; verify unusual characters")
            if ext in {".html", ".htm"}:
                parser = HTMLText()
                parser.feed(text)
                text = "".join(parser.parts)
                urls.update(parser.links)
            for index, paragraph in enumerate(re.split(r"\n\s*\n", text), 1):
                if not add("block " + str(index), paragraph):
                    break
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            if reader.is_encrypted:
                notes.append("Encrypted PDF; extraction may be unavailable")
            for index, page in enumerate(reader.pages, 1):
                for annotation in page.get("/Annots", []):
                    action = annotation.get_object().get("/A", {})
                    if hasattr(action, "get_object"):
                        action = action.get_object()
                    if action.get("/URI"):
                        urls.add(str(action["/URI"]))
                if not add("page " + str(index), page.extract_text()):
                    break
            notes.append("PDF text does not validate figures, layout, signatures or attachments")
        elif ext == ".docx":
            from docx import Document
            doc = Document(path)
            # Walk the original body order so table text stays near its paragraph context.
            from docx.oxml.ns import qn
            for index, node in enumerate(doc.element.body, 1):
                text = " ".join(element.text or "" for element in node.iter(qn("w:t")))
                if not add("body block " + str(index), text):
                    break
            notes.append("Word extraction excludes layout, revisions, embedded media and some headers")
        elif ext == ".pptx":
            from pptx import Presentation
            deck = Presentation(path)

            def shapes_text(shapes):
                parts = []
                for shape in shapes:
                    if getattr(shape, "has_text_frame", False):
                        parts.append(shape.text_frame.text)
                    if getattr(shape, "has_table", False):
                        parts.extend(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
                    if hasattr(shape, "shapes"):
                        parts.extend(shapes_text(shape.shapes))
                return parts

            for index, slide in enumerate(deck.slides, 1):
                if not add("slide " + str(index), "\n".join(shapes_text(slide.shapes))):
                    break
                if slide.has_notes_slide:
                    if not add("slide " + str(index) + " notes", slide.notes_slide.notes_text_frame.text):
                        break
            notes.append("Slide extraction excludes visual layout, animations and embedded media")
        elif ext == ".xlsx":
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=False)
            try:
                for sheet in book:
                    for row in sheet.iter_rows():
                        values = [str(cell.value) if cell.value is not None else "" for cell in row]
                        if any(values) and not add(sheet.title + " row " + str(row[0].row), " | ".join(values)):
                            break
                    if used >= max_chars:
                        break
            finally:
                book.close()
            notes.append("Spreadsheet text preserves formula strings, not formatting or calculation equivalence")
        else:
            return {"status": "unsupported_format", "units": [], "urls": [], "notes": ["Export legacy or native cloud formats to a supported format"]}
        if ext in {".docx", ".pptx", ".xlsx"}:
            with zipfile.ZipFile(path) as archive:
                for entry in archive.infolist():
                    if entry.filename.endswith(".rels") and entry.file_size < 5_000_000:
                        root = ElementTree.fromstring(archive.read(entry))
                        urls.update(element.attrib["Target"] for element in root if element.attrib.get("TargetMode") == "External" and "Target" in element.attrib)
        status = "truncated" if truncated else "extracted" if units else "needs_ocr_or_empty"
        return {"status": status, "units": units, "urls": sorted(urls), "notes": notes}
    except ImportError as error:
        return {"status": "missing_dependency", "units": [], "urls": [], "notes": [str(error)]}
    except Exception as error:
        return {"status": "extraction_error", "units": units, "urls": sorted(urls), "notes": notes + [type(error).__name__ + ": " + str(error)]}


def photo(path, ocr=False):
    result = {"status": "not_decoded", "width": None, "height": None, "pixel_sha256": None, "phash": None, "capture_date": None, "ocr_text": "", "notes": []}
    try:
        from PIL import Image, ImageOps, ImageStat
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as original:
                result["capture_date"] = original.getexif().get(36867) or original.getexif().get(306)
                if getattr(original, "n_frames", 1) != 1:
                    result["status"] = "multiframe_not_compared"
                    result["notes"].append("Animation or multipage image: full byte hash only")
                    return result
                oriented = ImageOps.exif_transpose(original).convert("RGBA")
                result["width"], result["height"] = oriented.size
                payload = str(oriented.size).encode("ascii") + oriented.tobytes()
                result["pixel_sha256"] = hashlib.sha256(payload).hexdigest()
                gray = oriented.convert("L")
                if ImageStat.Stat(gray).stddev[0] < 10:
                    result["notes"].append("Low-information image; perceptual matching skipped")
                else:
                    try:
                        import imagehash
                        result["phash"] = str(imagehash.phash(oriented.convert("RGB")))
                    except ImportError:
                        result["notes"].append("Install analysis extras for perceptual photo matching")
                if ocr:
                    try:
                        import pytesseract
                        result["ocr_text"] = pytesseract.image_to_string(oriented)[:500_000]
                    except Exception as error:
                        result["notes"].append("OCR unavailable: " + str(error))
                result["status"] = "decoded"
    except ImportError as error:
        result["status"] = "missing_dependency"
        result["notes"].append(str(error))
    except Exception as error:
        result["status"] = "decode_error"
        result["notes"].append(type(error).__name__ + ": " + str(error))
    return result
