"""Generate disposable examples; never reads the user's real library."""

import argparse
import json
import shutil
from pathlib import Path


def create(destination):
    root = Path(destination)
    if root.exists():
        raise ValueError("Demo directory must not already exist")
    for year in ["2019", "2024"]:
        (root / year).mkdir(parents=True)
    text = "Backup and recovery\n\nKeep original data, validate backups, and review duplicate files before cleanup.\n\nA recovery plan should preserve original source references and verified checksums.\n"
    first = root / "2019" / "backup-guide.txt"
    first.write_text(text, encoding="utf-8")
    shutil.copyfile(first, root / "2024" / "backup-guide-copy.txt")
    (root / "2024" / "backup-notes.md").write_text(text + "\nRetain offline copies for disaster recovery. https://example.com/backup\n", encoding="utf-8")
    (root / "2024" / "garden-notes.txt").write_text("Garden irrigation and plant care\n\n" + "Water plants according to soil conditions and protect new leaves from excessive heat. " * 8, encoding="utf-8")
    try:
        from PIL import Image, ImageDraw, PngImagePlugin
        image = Image.new("RGB", (320, 200), "#ffffff")
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 240, 140), fill="#117b68")
        draw.ellipse((150, 70, 300, 190), fill="#264d89")
        image.save(root / "2019" / "photo.png")
        shutil.copyfile(root / "2019" / "photo.png", root / "2024" / "photo-copy.png")
        info = PngImagePlugin.PngInfo()
        info.add_text("description", "Same pixels but additional metadata; review only")
        image.save(root / "2024" / "photo-with-metadata.png", pnginfo=info)
    except ImportError:
        pass
    try:
        from reportlab.pdfgen import canvas
        pdf = canvas.Canvas(str(root / "2024" / "backup-reference.pdf"))
        pdf.drawString(72, 750, "Backup and recovery reference")
        pdf.drawString(72, 725, "Keep original data, validate backups, and review duplicate files before cleanup.")
        pdf.save()
        from pptx import Presentation
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Backup and recovery"
        slide.placeholders[1].text = text
        deck.save(root / "2024" / "backup-slides.pptx")
    except ImportError:
        pass
    print(json.dumps({"demo_source": str(root.resolve()), "files": len(list(root.rglob("*.*")))}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    create(parser.parse_args().destination)
