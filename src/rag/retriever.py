"""მონაკვეთების მოძიება BM25-ით და კონტექსტის აწყობა LLM-ისთვის.

რანჟირება რელევანტურობითაა, მაგრამ ორი კორექციით.

**1. წყაროს უპირატესობა ქულას არ ცვლის.** თუ საცნობარო წყაროს
ხელოვნურად ჩამოვწევთ, მოდელი მას ვეღარ დაინახავს და ვერც იტყვის, რომ
FAQ სხვას ამბობს — ხოლო მუხლი 1.4 სწორედ ამას ითხოვს. ამიტომ
უპირატესობა კონტექსტში მეტამონაცემად მიდის და არა ქულაში.

**2. მოქმედი პოლიტიკის გარანტირებული ადგილი.** BM25 მოკლე ჩანაწერებს
უპირატესობას ანიჭებს, FAQ-ის პასუხები კი ორწინადადებიანია — შედეგად
ისინი ვიწროვებენ ვრცელ მუხლებს. გაზომვით: კითხვაზე „რამდენი დღე
შემიძლია ვიმუშაო სახლიდან?“ პირველი ოთხივე შედეგი FAQ იყო და მოქმედი
წესი (დისტანციური მუშაობის პოლიტიკა, მუხლი 4.1) კონტექსტში საერთოდ
არ ხვდებოდა. ამიტომ შედეგებში მინიმუმ `min_authoritative` ადგილი
მოქმედი პოლიტიკისთვისაა დაცული.

ასევე: ერთი მუხლის რამდენიმე ნაწილიდან საუკეთესო რჩება, რომ top-k
ერთმა გრძელმა მუხლმა არ ამოწუროს.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

from rank_bm25 import BM25Okapi

from src.config import INDEX_DIR
from src.rag.catalog import TIER_POLICY
from src.rag.index import INDEX_FILE
from src.rag.tokenizer import tokenize_query

DEFAULT_CANDIDATES = 25
DEFAULT_TOP_K = 5
MIN_AUTHORITATIVE = 2

# სუსტი დამხმარე ფრაგმენტების გაფილტვრა
MIN_SCORE = 0.5

# თემის ზღვარი: თუ საუკეთესო დამთხვევაც ამაზე სუსტია, პასუხი
# დოკუმენტებში არ არის და ცარიელ სიას ვაბრუნებთ.
#
# ზღვარი გაზომილია და არა შერჩეული: 11 რეალურ კითხვაზე (ტიპოიანის
# ჩათვლით) საუკეთესო ქულა 10.8–29.8 დიაპაზონშია, 5 უაზრო კითხვაზე კი
# 3.8–10.6.
#
# სრული გამიჯვნა შეუძლებელია და ეს განზრახ არ არის დამალული: უაზრო
# კითხვა, რომელიც დოკუმენტების ლექსიკას იყენებს („რა ფერია ოფისის
# კატა?“ — 10.6), თითქმის იმავე ქულას იღებს, რასაც სუსტი რეალური
# კითხვა (10.8). 10.0 ყველა რეალურ კითხვას ატარებს და აშკარად უცხო
# თემებს (3.8–8.2) აჩერებს; დანარჩენზე პასუხისმგებლობა prompt-ს აქვს,
# რომელიც კონტექსტში პასუხის არარსებობისას ამას პირდაპირ ამბობს.
#
# ქულა BM25-ისაა და ნორმალიზებული არ არის, ამიტომ ინდექსის ან
# ტოკენიზაციის ცვლილებისას თავიდან უნდა გაიზომოს.
RELEVANCE_FLOOR = 10.0

# ტიპოების გასწორება: მხოლოდ საკმარისად გრძელ ფუძეებზე და მკაცრი ზღვრით,
# რომ შემთხვევითმა დამთხვევამ ძიება არ გააბინძუროს.
MIN_FUZZY_LENGTH = 4
FUZZY_CUTOFF = 0.8


@dataclass(frozen=True)
class RetrievedChunk:
    score: float
    citation: str
    doc_title: str
    doc_version: str
    status: str
    tier: int
    tier_label: str
    article_label: str
    article_title: str | None
    superseded_by: str | None
    text: str

    @property
    def is_authoritative(self) -> bool:
        return self.tier >= TIER_POLICY and self.superseded_by is None


class IndexNotBuilt(FileNotFoundError):
    pass


class Retriever:
    def __init__(self, index_dir: Path | None = None) -> None:
        path = (index_dir or INDEX_DIR) / INDEX_FILE
        if not path.exists():
            raise IndexNotBuilt(
                f"ინდექსი არ არსებობს: {path}. გაუშვით `python -m src.rag.index`."
            )
        self._records: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        self._bm25 = BM25Okapi([record["tokens"] for record in self._records])
        self._vocabulary: tuple[str, ...] = tuple(
            sorted({token for record in self._records for token in record["tokens"]})
        )

    def __len__(self) -> int:
        return len(self._records)

    def repair_typos(self, tokens: list[str]) -> list[str]:
        """ინდექსში არარსებულ ფუძეებს ყველაზე ახლო ვარიანტით ანაცვლებს.

        BM25 ზუსტ დამთხვევაზე მუშაობს, ანუ ერთი ასოს შეცდომა კითხვას
        სრულიად აცდენს: „გადამდის მოომდევნო წელზე“ არაფერს აბრუნებდა.
        მოკლე ტოკენებს არ ვეხებით — იქ შემთხვევითი დამთხვევის რისკი
        დიდია და სარგებელი მცირე.
        """
        repaired: list[str] = []
        for token in tokens:
            if len(token) < MIN_FUZZY_LENGTH or token in self._vocabulary:
                repaired.append(token)
                continue
            close = get_close_matches(
                token, self._vocabulary, n=2, cutoff=FUZZY_CUTOFF
            )
            repaired.extend(close or [token])
        return repaired

    def search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        candidates: int = DEFAULT_CANDIDATES,
        min_score: float = MIN_SCORE,
        min_authoritative: int = MIN_AUTHORITATIVE,
        relevance_floor: float = RELEVANCE_FLOOR,
    ) -> list[RetrievedChunk]:
        """ყველაზე რელევანტური მონაკვეთები კითხვისთვის.

        თუ საუკეთესო დამთხვევა `relevance_floor`-ზე სუსტია, ცარიელი სია
        ბრუნდება — ასისტენტმა მკაფიოდ უნდა თქვას, რომ პასუხი
        დოკუმენტებში ვერ მოიძებნა.
        """
        pool = self._candidate_pool(query, candidates, min_score)
        if not pool or pool[0].score < relevance_floor:
            return []

        selected = pool[:top_k]

        # მოქმედი პოლიტიკისთვის დაცული ადგილები
        missing = min_authoritative - sum(1 for c in selected if c.is_authoritative)
        if missing > 0:
            reserves = [
                chunk
                for chunk in pool[top_k:]
                if chunk.is_authoritative
            ][:missing]
            if reserves:
                keep = [c for c in selected if c.is_authoritative]
                fillers = [c for c in selected if not c.is_authoritative]
                drop = len(reserves)
                selected = keep + fillers[: max(0, len(fillers) - drop)] + reserves

        return sorted(selected, key=lambda c: c.score, reverse=True)

    def _candidate_pool(
        self, query: str, candidates: int, min_score: float
    ) -> list[RetrievedChunk]:
        """რანჟირებული კანდიდატები, მუხლზე ერთი საუკეთესო ნაწილით."""
        tokens = self.repair_typos(tokenize_query(query))
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        seen_articles: set[tuple[str, str | None]] = set()
        pool: list[RetrievedChunk] = []

        for position in ranked:
            score = float(scores[position])
            if score < min_score or len(pool) >= candidates:
                break

            record = self._records[position]
            key = (record["doc_code"], record["article_no"])
            if key in seen_articles:
                continue  # ერთი მუხლიდან მხოლოდ საუკეთესო ნაწილი
            seen_articles.add(key)

            pool.append(
                RetrievedChunk(
                    score=round(score, 3),
                    citation=record["citation"],
                    doc_title=record["doc_title"],
                    doc_version=record["doc_version"],
                    status=record["status"],
                    tier=record["tier"],
                    tier_label=record["tier_label"],
                    article_label=record["article_label"],
                    article_title=record["article_title"],
                    superseded_by=record["superseded_by"],
                    text=record["text"],
                )
            )

        return pool


def build_context(results: list[RetrievedChunk]) -> str:
    """მოძიებულ მონაკვეთებს LLM-ის კონტექსტად აწყობს.

    თითოეულ ფრაგმენტს ახლავს ციტირება და წყაროს სტატუსი, რომ მოდელმა
    წინააღმდეგობისას მოქმედ დოკუმენტს დაეყრდნოს და მოძველებული წყარო
    ცალკე ახსენოს (მუხლი 1.4).
    """
    if not results:
        return ""

    blocks: list[str] = []
    for number, result in enumerate(results, start=1):
        header = f"[{number}] {result.citation}"
        notes = [f"წყაროს ტიპი: {result.tier_label}"]
        if result.superseded_by:
            notes.append(f"ეს თავი ჩანაცვლებულია: {result.superseded_by}")
        blocks.append(f"{header}\n({'; '.join(notes)})\n{result.text}")

    return "\n\n---\n\n".join(blocks)
