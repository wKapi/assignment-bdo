"""ტექსტის დაჭრა მუხლებად.

დოკუმენტები დანომრილი მუხლებისგან შედგება, ამიტომ ბუნებრივი საზღვარი
სათაურია და არა ფიქსირებული სიგრძე — ასე ციტირება ზუსტი გამოდის.

ორი სახის ნუმერაცია გვხვდება:

* პოლიტიკები და სახელმძღვანელო — `4`, `4.1`, `12.3`;
* FAQ — ქართული ასოებით: `ა. შვებულება`, `ა.3 რა ხდება …`.

ნომერი ორნიშნა ციფრით შემოვფარგლეთ, რადგან სათაურის ბლოკში წერია
„2026 წლის 1 მარტიდან“ — ის მუხლის ნომრად არ უნდა ჩაითვალოს.

ძალიან გრძელი მუხლი overlap-ით იჭრება, სტრიქონის საზღვარზე, რომ
markdown-ცხრილის რიგები შუაზე არ გაწყდეს.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from src.rag.catalog import DocumentMeta

NUMERIC_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\.?\s+(\S.*)$")
GEORGIAN_HEADING = re.compile(r"^([ა-ჰ]\.(?:\d{1,2})?)\s+(\S.*)$")

MAX_CHARS = 800
OVERLAP_CHARS = 120

# სათაურის დასახელება მოკლეა და წინადადების პუნქტუაციით არ მთავრდება.
# ამის გარეშე ციფრით დაწყებული წინადადებები მუხლებად ითვლება:
# „5 დღეზე მეტის გადატანა დასაშვებია…“ (მუხლი 4.7-ის ტექსტი) „მუხლი 5“
# ხდებოდა და ციტირება მცდარი გამოდიოდა.
MAX_TITLE_CHARS = 70
SENTENCE_ENDINGS = ".;:,"


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    filename: str
    doc_title: str
    doc_code: str
    doc_version: str
    effective_date: str
    status: str
    tier: int
    tier_label: str
    article_no: str | None
    article_title: str | None
    article_label: str
    """„მუხლი 4.4“ ან „კითხვა ა.3“ — ციტირებისთვის."""
    superseded_by: str | None
    citation: str
    text: str

    def as_dict(self) -> dict:
        return asdict(self)


class _Sequence:
    """მუხლების ნუმერაციის მიმდევრობა ერთი დოკუმენტის ფარგლებში.

    ნამდვილი სათაურები ზრდადია (1, 1.1, 1.2, 2, 2.1 …). ეს ტექსტში
    შემთხვევით ციფრებს ასხვავებს სათაურებისგან: მუხლი 4-ის შიგნით
    შემხვედრი „1 დეკემბრიდან 20 დეკემბრის ჩათვლით:“ უკან იხევს და
    სათაურად აღარ ითვლება.
    """

    def __init__(self) -> None:
        self.chapter = 0
        self.section = 0

    def accepts(self, number: str) -> bool:
        parts = number.split(".")
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return True  # ქართულასოებიანი ნუმერაცია (FAQ)

        if len(numbers) == 1:
            chapter = numbers[0]
            if chapter > self.chapter:
                self.chapter, self.section = chapter, 0
                return True
            return False

        chapter, section = numbers
        if chapter == self.chapter and section > self.section:
            self.section = section
            return True
        if chapter == self.chapter + 1 and section == 1:
            self.chapter, self.section = chapter, section
            return True
        return False


def match_heading(line: str, sequence: _Sequence | None = None) -> tuple[str, str] | None:
    """სტრიქონი მუხლის სათაურია თუ არა → (ნომერი, დასახელება).

    `sequence`-ის გადაცემისას დამატებით მოწმდება ნუმერაციის ზრდადობა.
    """
    match = GEORGIAN_HEADING.match(line)
    if match:
        title = match.group(2).strip()
        if title:
            return match.group(1).rstrip("."), title

    match = NUMERIC_HEADING.match(line)
    if not match:
        return None

    number, title = match.group(1).rstrip("."), match.group(2).strip()
    if not title or len(title) > MAX_TITLE_CHARS:
        return None
    if title[-1] in SENTENCE_ENDINGS:
        return None
    if sequence is not None and not sequence.accepts(number):
        return None
    return number, title


def _article_label(article_no: str | None, meta: DocumentMeta) -> str:
    if article_no is None:
        return "სათაურის ბლოკი"
    if article_no[0].isdigit():
        return f"მუხლი {article_no}"
    return f"კითხვა {article_no}"


def _split_long(lines: list[str]) -> list[str]:
    """გრძელ მუხლს overlap-ით ჭრის, სტრიქონის საზღვარზე."""
    blocks: list[str] = []
    current: list[str] = []
    length = 0

    for line in lines:
        if current and length + len(line) + 1 > MAX_CHARS:
            blocks.append("\n".join(current))
            # overlap — ბოლო სტრიქონები, სანამ ლიმიტს არ მივაღწევთ
            tail: list[str] = []
            tail_length = 0
            for previous in reversed(current):
                if tail_length + len(previous) > OVERLAP_CHARS:
                    break
                tail.insert(0, previous)
                tail_length += len(previous) + 1
            current = tail
            length = tail_length
        current.append(line)
        length += len(line) + 1

    if current:
        blocks.append("\n".join(current))
    return blocks


def chunk_document(lines: list[str], meta: DocumentMeta) -> list[Chunk]:
    """სტრიქონების სიას მუხლებად დაჭრილ chunk-ებად აქცევს."""
    sections: list[tuple[str | None, str | None, list[str]]] = []
    article_no: str | None = None
    article_title: str | None = None
    buffer: list[str] = []
    sequence = _Sequence()

    for line in lines:
        heading = match_heading(line, sequence)
        if heading:
            if buffer:
                sections.append((article_no, article_title, buffer))
            article_no, article_title = heading
            buffer = [f"{article_no} {article_title}"]
        else:
            buffer.append(line)

    if buffer:
        sections.append((article_no, article_title, buffer))

    chunks: list[Chunk] = []
    for number, title, body in sections:
        label = _article_label(number, meta)
        superseded = meta.section_superseded_by(number)
        citation = (
            f"{meta.citation}, {label}" if number else meta.citation
        )

        # მხოლოდ სათაურისგან შემდგარი ნაწილი (თავის დასახელება ქვემუხლების
        # გარეშე) შინაარსს არ ატარებს და კონტექსტში ადგილს ტყუილად იკავებს
        if number and len(body) == 1:
            continue

        for part, text in enumerate(_split_long(body)):
            if not text.strip():
                continue
            suffix = f"#{part}" if part else ""
            chunks.append(
                Chunk(
                    chunk_id=f"{meta.code}:{number or 'head'}{suffix}",
                    filename=meta.filename,
                    doc_title=meta.title,
                    doc_code=meta.code,
                    doc_version=meta.version,
                    effective_date=meta.effective_date,
                    status=meta.status,
                    tier=meta.tier,
                    tier_label=meta.tier_label,
                    article_no=number,
                    article_title=title,
                    article_label=label,
                    superseded_by=superseded,
                    citation=citation,
                    text=text,
                )
            )
    return chunks
