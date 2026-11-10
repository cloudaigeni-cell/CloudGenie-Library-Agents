"""Build the architecture artwork and printable guide from the shipped Markdown."""

import html
import re
import textwrap
from pathlib import Path
from xml.etree import ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image, Preformatted, KeepTogether
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
W, H = 1200, 1200


def architecture():
    target = DOCS / "architecture.pdf"
    pdf = canvas.Canvas(str(target), pagesize=(W, H))
    svg = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "viewBox": f"0 0 {W} {H}", "width": str(W), "height": str(H), "role": "img", "aria-label": "CloudGenie coordinator and year specialists with reviewed local cleanup"})
    ET.SubElement(svg, "rect", {"width": str(W), "height": str(H), "fill": "white"})
    pdf.setFillColor(colors.white)
    pdf.rect(0, 0, W, H, fill=1, stroke=0)

    def text(x, y, value, size=19, bold=False, anchor="middle", color="#17212b"):
        font = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFont(font, size)
        pdf.setFillColor(colors.HexColor(color))
        if anchor == "middle":
            pdf.drawCentredString(x, H - y, value)
        else:
            pdf.drawString(x, H - y, value)
        element = ET.SubElement(svg, "text", {"x": str(x), "y": str(y), "font-family": "Arial, sans-serif", "font-size": str(size), "font-weight": "700" if bold else "400", "text-anchor": anchor, "fill": color})
        element.text = value

    def box(x, y, width, height, title, detail, fill):
        pdf.setStrokeColor(colors.HexColor("#9ba5ae"))
        pdf.setFillColor(colors.HexColor(fill))
        pdf.roundRect(x, H - y - height, width, height, 7, stroke=1, fill=1)
        ET.SubElement(svg, "rect", {"x": str(x), "y": str(y), "width": str(width), "height": str(height), "rx": "7", "fill": fill, "stroke": "#9ba5ae"})
        text(x + width / 2, y + 29, title, 21, True)
        for index, line in enumerate(detail):
            text(x + width / 2, y + 54 + index * 22, line, 17)

    def line(points, arrow=True):
        pdf.setStrokeColor(colors.HexColor("#5b6874"))
        pdf.setLineWidth(2)
        path = pdf.beginPath()
        path.moveTo(points[0][0], H - points[0][1])
        for x, y in points[1:]:
            path.lineTo(x, H - y)
        pdf.drawPath(path)
        ET.SubElement(svg, "polyline", {"points": " ".join(str(x) + "," + str(y) for x, y in points), "fill": "none", "stroke": "#5b6874", "stroke-width": "2"})
        if arrow:
            x, y = points[-1]
            previous = points[-2]
            if x == previous[0]:
                vertices = [(x, y), (x - 5, y - 9), (x + 5, y - 9)] if y > previous[1] else [(x, y), (x - 5, y + 9), (x + 5, y + 9)]
            else:
                vertices = [(x, y), (x - 9, y - 5), (x - 9, y + 5)]
            path = pdf.beginPath()
            path.moveTo(vertices[0][0], H - vertices[0][1])
            for vx, vy in vertices[1:]:
                path.lineTo(vx, H - vy)
            path.close()
            pdf.setFillColor(colors.HexColor("#5b6874"))
            pdf.drawPath(path, stroke=0, fill=1)
            ET.SubElement(svg, "polygon", {"points": " ".join(str(vx) + "," + str(vy) for vx, vy in vertices), "fill": "#5b6874"})

    text(60, 49, "CloudGenie Library Agents", 34, True, "start")
    text(60, 83, "Read sources, collect evidence, consolidate knowledge, then review cleanup", 19, False, "start")
    box(60, 117, 1080, 76, "Inputs stay read-only during analysis", ["Extracted Google Takeout and local folders | No cloud credentials or deletion"], "#e9f2fa")
    box(370, 237, 460, 79, "Main coordinator and inventory", ["Discover files, infer years, schedule jobs"], "#f1f3f5")
    line([(600, 193), (600, 237)])
    for x, label in [(60, "Year 2019"), (440, "Year 2024"), (820, "Every selected year")]:
        box(x, 365, 320, 75, label, ["One queue per format specialist"], "#e9f5ef")
        line([(600, 316), (600, 338), (x + 160, 338), (x + 160, 365)])
    text(600, 476, "Each year can dispatch all three specialist roles", 18)
    for x, title, detail, fill in [(60, "Document agent", ["PDF PPTX DOCX XLSX text", "Text, notes, tables and URLs"], "#e9f5ef"), (440, "Photo agent", ["EXIF, pixels and pHash", "Optional image OCR"], "#edf2fc"), (820, "Hash-only agent", ["Other files and videos", "Complete SHA-256 bytes"], "#f1f3f5")]:
        box(x, 513, 320, 103, title, detail, fill)
        line([(x + 160, 440), (x + 160, 455)], arrow=False)
        line([(x + 160, 490), (x + 160, 513)])
    line([(220, 490), (980, 490)], arrow=False)
    box(60, 665, 1080, 77, "Global catalog, extraction cache and event history", ["All selected years combine here | Source IDs, checksums, dates and provenance"], "#f1f3f5")
    for x in [220, 600, 980]:
        line([(x, 616), (x, 640), (600, 640)], arrow=False)
    line([(600, 640), (600, 665)])
    box(60, 787, 520, 81, "Duplicate evidence agent", ["Exact bytes vs pixels, text and visual similarity"], "#fff0ea")
    box(620, 787, 520, 81, "Subject and consolidation agents", ["Topic reading packs with source references"], "#e9f5ef")
    line([(320, 742), (320, 787)])
    line([(880, 742), (880, 787)])
    box(60, 912, 520, 78, "Human approves selected exact-byte copies", ["No keeper may also be scheduled for removal"], "#fff7d9")
    box(620, 912, 520, 78, "Derived reading packs", ["All originals retained | AI summaries optional"], "#e9f5ef")
    line([(320, 868), (320, 912)])
    line([(880, 868), (880, 912)])
    box(60, 1033, 520, 80, "Cleanup agent verifies and quarantines", ["Rehash originals, verify backup, record journal"], "#fff7d9")
    box(620, 1033, 245, 95, "Restore", ["No overwrites", "Backups retained"], "#edf2fc")
    box(895, 1033, 245, 95, "Purge locally", ["Second approval", "Typed confirmation"], "#fdebee")
    line([(320, 990), (320, 1033)])
    line([(580, 1073), (620, 1073)])
    line([(580, 1095), (598, 1095), (598, 1150), (1017, 1150), (1017, 1128)])
    text(60, 1180, "Local export cleanup does not delete Google Photos originals or confirm cloud space savings", 17, False, "start")
    pdf.save()
    ET.ElementTree(svg).write(DOCS / "architecture.svg", encoding="utf-8", xml_declaration=True)
    import pypdfium2 as pdfium
    rendered = pdfium.PdfDocument(str(target))
    rendered[0].render(scale=1.5).to_pil().save(DOCS / "architecture.png")
    rendered.close()


def inline(value):
    value = html.escape(value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda match: '<link href="' + match.group(2) + '">' + match.group(1) + '</link>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    return value


def markdown_flow(text, styles):
    lines = text.splitlines()
    flow, index = [], 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip()
            index += 1
            block = []
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            if language == "mermaid":
                flow.append(Paragraph("Editable Mermaid diagrams are included in the accompanying architecture files.", styles["Small"]))
                continue
            wrapped = []
            for code in block:
                wrapped.extend(textwrap.wrap(code, width=87, replace_whitespace=False, drop_whitespace=False, subsequent_indent="  ") or [""])
            group = [Preformatted("\n".join(wrapped), styles["CodeBlock"]), Spacer(1, 7)]
            if flow and isinstance(flow[-1], Paragraph) and flow[-1].style.name == "LeadIn":
                group.insert(0, flow.pop())
                if flow and isinstance(flow[-1], Paragraph) and flow[-1].style.name in {"Heading1", "Heading2"}:
                    group.insert(0, flow.pop())
            flow.append(KeepTogether(group))
            continue
        if line.startswith("|"):
            data = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[:\- ]+", cell) for cell in cells):
                    data.append([Paragraph(inline(cell), styles["TableText"]) for cell in cells])
                index += 1
            count = len(data[0])
            widths = [128, 383] if count == 2 else [115, 211, 185] if count == 3 else [97, 128, 154, 132] if count == 4 else [511 / count] * count
            table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edf3")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")]), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9d9")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
            flow += [table, Spacer(1, 10)]
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            flow.append(Paragraph(inline(title), styles["Heading1" if level <= 2 else "Heading2"]))
            index += 1
            continue
        if line.startswith("- "):
            flow.append(Paragraph(inline(line[2:]), styles["BulletText"], bulletText="-"))
            index += 1
            continue
        paragraphs = [line]
        index += 1
        while index < len(lines) and lines[index].strip() and not lines[index].startswith(("#", "- ", "|", "```")):
            paragraphs.append(lines[index])
            index += 1
        paragraph_text = " ".join(paragraphs)
        flow.append(Paragraph(inline(paragraph_text), styles["LeadIn"] if paragraph_text.rstrip().endswith(":") else styles["BodyText"]))
    return flow


def guide():
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "Helvetica-Bold"
    styles["Title"].fontSize = 25
    styles["Title"].leading = 30
    styles["Title"].textColor = colors.black
    styles["Title"].alignment = 0
    for key, size, leading in [("Heading1", 17, 22), ("Heading2", 13, 18)]:
        styles[key].fontName = "Helvetica-Bold"
        styles[key].fontSize = size
        styles[key].leading = leading
        styles[key].textColor = colors.black
        styles[key].spaceBefore = 15
        styles[key].spaceAfter = 9
        styles[key].keepWithNext = True
    styles["BodyText"].fontName = "Helvetica"
    styles["BodyText"].fontSize = 10
    styles["BodyText"].leading = 14.5
    styles["BodyText"].spaceAfter = 8
    styles.add(ParagraphStyle("LeadIn", parent=styles["BodyText"], keepWithNext=True))
    styles.add(ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8.5, leading=12, textColor=colors.HexColor("#4c5965")))
    styles.add(ParagraphStyle("TableText", parent=styles["BodyText"], fontSize=8.5, leading=11.5, spaceAfter=0))
    styles.add(ParagraphStyle("BulletText", parent=styles["BodyText"], leftIndent=12, bulletIndent=0, spaceAfter=6))
    styles.add(ParagraphStyle("CodeBlock", fontName="Courier", fontSize=8, leading=11, backColor=colors.HexColor("#f3f5f7"), borderPadding=8, spaceBefore=7, spaceAfter=9))
    destination = DOCS / "CloudGenie-Library-Agents-Guide.pdf"
    document = SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=45, title="CloudGenie Library Agents Architecture and Operations Guide", author="CloudGenie")
    story = [Paragraph("CloudGenie Library Agents", styles["Title"]), Paragraph("Architecture and Operations Guide", styles["Heading1"]), Paragraph("Version 1.0 | 10 November 2026", styles["Small"]), Spacer(1, 17)]
    introduction = ["This framework helps you reduce the number of files you need to navigate while retaining a complete record of the originals. A coordinator assigns yearly document, photo and hash workers, then combines their evidence across the selected library.", "Start with an extracted Google Takeout copy. The scan builds an inventory, separates exact duplicates from similar items, and creates subject reading packs with references back to their sources. No scan command changes original data.", "Cleanup is an independent reviewed workflow. Exact-byte copies may be quarantined only after approval and fresh verification. Permanent purge requires another approval and typed confirmation. Pixel similarity, topic grouping and AI summaries cannot authorize deletion.", "MCP is optional. The application runs directly on Windows, WSL Ubuntu or a container. Google Photos cloud deletion is not implemented; local export cleanup does not free cloud quota."]
    story.extend(Paragraph(value, styles["BodyText"]) for value in introduction)
    story += [Paragraph("How to use this guide", styles["Heading1"]), Paragraph("Review the architecture illustration, follow the installation and demo instructions, and inspect the generated inventory before using any cleanup commands. The operations section covers approval, quarantine, restore and optional purge. The technical appendix documents worker contracts, data structures and scaling limits.", styles["BodyText"]), Paragraph("The accompanying Markdown files contain copyable commands and editable Mermaid diagram source. Source files and tests are included in the release package.", styles["BodyText"]), PageBreak(), Paragraph("Architecture Illustration", styles["Heading1"]), Image(str(DOCS / "architecture.png"), width=511, height=511 * H / W), Spacer(1, 10), Paragraph("Year workers all contribute to the shared catalog. Similarity and consolidation produce review evidence; only a separately approved exact-byte plan reaches local cleanup. See the full-resolution PNG, SVG and PDF for an enlarged view.", styles["Small"]), PageBreak()]
    readme = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    story += markdown_flow("\n".join(readme[1:]), styles)
    story += [PageBreak(), Paragraph("Technical Architecture Appendix", styles["Title"])]
    architecture_text = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    story += markdown_flow("\n".join(architecture_text[1:]), styles)

    def footer(page_canvas, doc):
        page_canvas.saveState()
        page_canvas.setFont("Helvetica", 8)
        page_canvas.setFillColor(colors.HexColor("#4c5965"))
        page_canvas.drawString(42, 25, "CloudGenie Library Agents | Architecture and Operations")
        page_canvas.drawRightString(A4[0] - 42, 25, str(doc.page))
        page_canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(destination)


if __name__ == "__main__":
    DOCS.mkdir(parents=True, exist_ok=True)
    architecture()
    guide()
