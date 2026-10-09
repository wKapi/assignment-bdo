"""დოკუმენტების წაკითხვა ტექსტად.

DOCX — `python-docx`: პარაგრაფები თავისი რიგით, ცხრილები markdown-ად
(რიცხვების ცხრილები პოლიტიკებში ხშირია და მათი დაკარგვა პასუხს ანგრევს).

PDF — `pypdf`: ტექსტური ფაილებია, OCR არ სჭირდება. ყოველ გვერდზე
მეორდება კოლონტიტული („შპს ნორთსტარ სერვისეზი | … | ვერსია 3.2 | შიდა
გამოყენებისთვის“ და „გვერდი N“) — ასეთი სტრიქონები იჭრება, თორემ
BM25-ში ყველა chunk ერთნაირად დაემთხვევა საერთო სიტყვებს.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

PAGE_MARKER = re.compile(r"^გვერდი\s+\d+$")

def _table_to_markdown(table: Table) -> str:
    """ცხრილს markdown-ად აქცევს, რომ chunk-ში სტრუქტურა არ დაიკარგოს."""
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    lines = ["| " + " | ".join(rows[0]) + " |",
             "|" + "|".join(["---"] * width) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _iter_block_items(document: Document):
    """პარაგრაფებსა და ცხრილებს დოკუმენტის თანმიმდევრობით აბრუნებს."""
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def load_docx(path: Path) -> list[str]:
    document = Document(str(path))
    lines: list[str] = []
    for block in _iter_block_items(document):
        if isinstance(block, Paragraph):
            text = " ".join(block.text.split())
            if text:
                lines.append(text)
        else:
            markdown = _table_to_markdown(block)
            if markdown:
                lines.extend(markdown.split("\n"))
    return lines


# PDF


def _boilerplate_lines(pages: list[str], min_repeats: int) -> set[str]:
    """სტრიქონები, რომლებიც გვერდების უმეტესობაზე მეორდება."""
    counts: Counter[str] = Counter()
    for page in pages:
        for line in {l.strip() for l in page.split("\n") if l.strip()}:
            counts[line] += 1
    return {line for line, n in counts.items() if n >= min_repeats}


def load_pdf(path: Path) -> list[str]:
    pages = [(page.extract_text() or "") for page in PdfReader(str(path)).pages]
    threshold = max(2, (len(pages) // 2) + 1)
    boilerplate = _boilerplate_lines(pages, threshold)

    lines: list[str] = []
    for page in pages:
        for raw in page.split("\n"):
            line = " ".join(raw.split())
            if not line or line in boilerplate or PAGE_MARKER.match(line):
                continue
            lines.append(line)
    return lines


def load_document(path: Path) -> list[str]:
    """ფაილს ტექსტის სტრიქონებად კითხულობს გაფართოების მიხედვით."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return load_docx(path)
    if suffix == ".pdf":
        return load_pdf(path)
    raise ValueError(f"მხარდაუჭერელი ფორმატი: {path.name}")
