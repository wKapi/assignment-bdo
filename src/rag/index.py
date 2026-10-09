"""RAG ინდექსის აგება.

გაშვება რეპოზიტორიის ფესვიდან:

    python -m src.rag.index

შედეგი იწერება `INDEX_DIR/chunks.json`-ში: chunk-ები მეტამონაცემებითა
და წინასწარ გამოთვლილი ტოკენებით. BM25 ობიექტი თავად არ ინახება —
ის ტოკენებიდან მილიწამებში აიწყობა და serialization-ის პრობლემა არ
გვაქვს.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.config import DOCUMENTS_DIR, INDEX_DIR
from src.rag.catalog import CATALOG
from src.rag.chunker import Chunk, chunk_document
from src.rag.loaders import load_document
from src.rag.tokenizer import tokenize

INDEX_FILE = "chunks.json"


def build_chunks(documents_dir: Path | None = None) -> list[Chunk]:
    """ყველა დოკუმენტს კითხულობს და chunk-ებად ჭრის."""
    source_dir = documents_dir or DOCUMENTS_DIR
    chunks: list[Chunk] = []

    for meta in CATALOG:
        path = source_dir / meta.filename
        if not path.exists():
            raise FileNotFoundError(f"დოკუმენტი ვერ მოიძებნა: {path}")
        lines = load_document(path)
        chunks.extend(chunk_document(lines, meta))

    return chunks


def build_index(
    documents_dir: Path | None = None, index_dir: Path | None = None
) -> Path:
    """ინდექსს აგებს და დისკზე წერს; აბრუნებს ფაილის გზას."""
    target_dir = index_dir or INDEX_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    chunks = build_chunks(documents_dir)
    # ინდექსირდება მუხლის სათაური + ტექსტი. დოკუმენტის სათაურის დამატებაც
    # ვცადე (რომ თემატურად სწორი ფაილის ყველა ნაწილს სუსტი ქულა მიეღო) —
    # გაზომვით მოგება არ მოიტანა და სხვა კითხვებს ოდნავ აბინძურებდა.
    payload = [
        {
            **chunk.as_dict(),
            "tokens": tokenize(f"{chunk.article_title or ''} {chunk.text}"),
        }
        for chunk in chunks
    ]

    path = target_dir / INDEX_FILE
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return path


def main() -> None:
    path = build_index()
    payload = json.loads(path.read_text(encoding="utf-8"))

    per_document: dict[str, int] = {}
    for item in payload:
        per_document[item["doc_title"]] = per_document.get(item["doc_title"], 0) + 1

    print(f"ინდექსი: {path}")
    print(f"სულ {len(payload)} ნაწილი {len(per_document)} დოკუმენტიდან:\n")
    for title, count in sorted(per_document.items(), key=lambda x: -x[1]):
        print(f"  {count:>4}  {title}")


if __name__ == "__main__":
    main()
