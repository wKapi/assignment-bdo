"""RAG-ის ტესტები — ჩატვირთვა, დაჭრა, ტოკენიზაცია, მოძიება."""

from __future__ import annotations

import pytest

from src.config import DOCUMENTS_DIR
from src.rag.catalog import BY_FILENAME, CATALOG, TIER_POLICY, TIER_REFERENCE
from src.rag.chunker import chunk_document, match_heading
from src.rag.index import build_chunks, build_index
from src.rag.loaders import load_document
from src.rag.retriever import Retriever, build_context
from src.rag.tokenizer import stem, tokenize, tokenize_query


#  სათაურების ამოცნობა

def test_numeric_headings():
    assert match_heading("4.4 მოთხოვნის წარდგენა") == ("4.4", "მოთხოვნის წარდგენა")
    assert match_heading("12. თვითმომსახურების არხები")[0] == "12"


def test_georgian_faq_headings():
    """FAQ-ის სათაურები ასოებითაა — რიცხვითი რეგექსი მათ ვერ დაიჭერს."""
    assert match_heading("ა.3 რა ხდება გამოუყენებელ დღეებთან?") == (
        "ა.3",
        "რა ხდება გამოუყენებელ დღეებთან?",
    )
    assert match_heading("ა. შვებულება") == ("ა", "შვებულება")


def test_year_in_header_is_not_a_heading():
    """„2026 წლის 1 მარტიდან“ მუხლად არ უნდა ჩაითვალოს."""
    assert match_heading("2026 წლის 1 იანვრიდან") is None


def test_plain_text_is_not_a_heading():
    assert match_heading("თანამშრომელი მოთხოვნას წარადგენს.") is None




def test_every_catalogued_document_exists():
    for meta in CATALOG:
        assert (DOCUMENTS_DIR / meta.filename).exists(), meta.filename


def test_pdf_boilerplate_is_removed():
    """ყოველ გვერდზე გამეორებული კოლონტიტული ინდექსში არ უნდა მოხვდეს."""
    lines = load_document(DOCUMENTS_DIR / "Information_Security_Policy_v3.2.pdf")
    assert not any("შიდა გამოყენებისთვის" in line for line in lines)
    assert not any(line.startswith("გვერდი ") for line in lines)
    assert len(lines) > 100  


def test_docx_tables_become_markdown():
    """მუხლი 4.1-ის სტაჟის ცხრილი არ უნდა დაიკარგოს."""
    lines = load_document(DOCUMENTS_DIR / "Leave_and_Absence_Policy_v4.0.docx")
    text = "\n".join(lines)
    assert "| 24 |" in text or "| 24 " in text
    assert "|---" in text



def test_faq_is_split_into_questions():
    meta = BY_FILENAME["Employee_FAQ_2025.docx"]
    chunks = chunk_document(load_document(DOCUMENTS_DIR / meta.filename), meta)
    numbers = {c.article_no for c in chunks}

    assert "ა.3" in numbers
    assert "ბ.1" in numbers
    assert len(chunks) > 20, "FAQ ერთ chunk-ად არ უნდა დარჩეს"


def test_citation_format():
    meta = BY_FILENAME["Leave_and_Absence_Policy_v4.0.docx"]
    chunks = chunk_document(load_document(DOCUMENTS_DIR / meta.filename), meta)
    article = next(c for c in chunks if c.article_no == "4.4")

    assert article.citation == "შვებულებისა და გაცდენის პოლიტიკა v4.0, მუხლი 4.4"
    assert article.tier == TIER_POLICY


def test_faq_citation_says_question_not_article():
    meta = BY_FILENAME["Employee_FAQ_2025.docx"]
    chunks = chunk_document(load_document(DOCUMENTS_DIR / meta.filename), meta)
    question = next(c for c in chunks if c.article_no == "ა.3")

    assert "კითხვა ა.3" in question.citation
    assert question.tier == TIER_REFERENCE


def test_superseded_handbook_chapters_are_flagged():
    """სახელმძღვანელოს მე-5 და მე-6 თავები ჩანაცვლებულია."""
    meta = BY_FILENAME["Employee_Handbook_v3.1.docx"]
    chunks = chunk_document(load_document(DOCUMENTS_DIR / meta.filename), meta)
    by_number = {c.article_no: c for c in chunks}

    assert "შვებულებისა და გაცდენის პოლიტიკა v4.0" in by_number["5.2"].superseded_by
    assert "დისტანციური" in by_number["6"].superseded_by
    assert by_number["7.1"].superseded_by is None


def test_long_articles_are_split_with_overlap():
    chunks = build_chunks()
    assert all(len(c.text) < 1200 for c in chunks)


# ტოკენიზაცია 


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("შვებულება", "შვებულ"),
        ("შვებულების", "შვებულ"),
        ("შვებულებას", "შვებულ"),
        ("შვებულებაზე", "შვებულ"),
    ],
)
def test_case_endings_collapse_to_one_stem(word, expected):
    assert stem(word) == expected


def test_tokenize_drops_punctuation():
    assert tokenize("რამდენი დღე?") == ["რამდენ", "დღე"]


def test_query_expansion_adds_domain_synonyms():
    """„სახლიდან“ დოკუმენტებში „დისტანციურად“ წერია."""
    assert "დისტანციურ" in tokenize_query("სახლიდან მუშაობა")
    assert "დისტანციურ" not in tokenize("სახლიდან მუშაობა")




#მოძიება
@pytest.fixture(scope="module")
def retriever(tmp_path_factory) -> Retriever:
    index_dir = tmp_path_factory.mktemp("index")
    build_index(index_dir=index_dir)
    return Retriever(index_dir=index_dir)


def test_index_covers_all_documents(retriever):
    assert len(retriever) > 200


def test_finds_the_governing_article(retriever):
    hits = retriever.search("რამდენი დღე გადადის მომდევნო წელზე?")
    citations = [h.citation for h in hits]
    assert any("მუხლი 4.7" in c for c in citations)


def test_contradicting_sources_are_both_returned(retriever):
    """მუხლი 1.4-ის სცენარი: მოქმედი პოლიტიკაც და მოძველებული FAQ-ც."""
    hits = retriever.search("რამდენი დღე შვებულება გადადის მომდევნო წელზე?")

    assert any(h.is_authoritative for h in hits)
    assert any(h.tier == TIER_REFERENCE for h in hits)


def test_authoritative_sources_are_always_present(retriever):
    """FAQ-ის მოკლე პასუხებმა მოქმედი პოლიტიკა არ უნდა გამოდევნოს."""
    for query in (
        "რამდენი დღე შემიძლია ვიმუშაო სახლიდან?",
        "შემიძლია გამოცდისთვის შვებულება ავიღო?",
        "რამდენი ხნით ადრე უნდა წარვადგინო შვებულების მოთხოვნა?",
    ):
        hits = retriever.search(query)
        assert sum(1 for h in hits if h.is_authoritative) >= 2, query


@pytest.mark.parametrize(
    "query",
    [
        "კვანტური ტელეპორტაციის ლიმიტი",
        "რამდენია პარკინგის ლიმიტი მარსზე?",
        "ვის ეკუთვნის დელფინების მოვლის დანამატი?",
    ],
)
def test_unknown_topic_returns_nothing(retriever, query):
    """დოკუმენტებში არარსებულ თემაზე ასისტენტს კონტექსტი არ უნდა მივცეთ."""
    assert retriever.search(query) == []


def test_empty_query_returns_nothing(retriever):
    assert retriever.search("   ") == []


def test_context_carries_citations_and_warnings(retriever):
    hits = retriever.search("რამდენი დღე შვებულება გადადის მომდევნო წელზე?")
    context = build_context(hits)

    assert "მუხლი 4.7" in context
    assert "საცნობარო მასალა" in context
    assert "---" in context


def test_empty_context_for_no_hits():
    assert build_context([]) == ""



@pytest.mark.parametrize(
    ("typo", "expected_article"),
    [
        ("რამდენი დღე შვებულება გადამდის მოომდევნო წელზე", "4.7"),
        ("როდის მჭირდბა სამედიცნო ცნობა", "6.3"),
    ],
)
def test_typos_still_find_the_right_article(retriever, typo, expected_article):
    """BM25 ზუსტ დამთხვევაზეა — ერთი ასოც კითხვას სრულიად აცდენდა."""
    citations = [h.citation for h in retriever.search(typo)]
    assert any(f"მუხლი {expected_article}" in c for c in citations), citations


def test_typo_repair_does_not_rescue_nonsense(retriever):
    """გასწორებამ უაზრო კითხვა ხელოვნურად არ უნდა „იპოვოს“."""
    assert retriever.search("კვანტური ტელეპორტაციის ლიმიტი") == []
    assert retriever.search("ვის ეკუთვნის დელფინების მოვლის დანამატი?") == []


def test_short_tokens_are_left_alone(retriever):
    assert retriever.repair_typos(["დღე", "ის"]) == ["დღე", "ის"]


# ცრუ სათაურები


def test_sentence_starting_with_a_number_is_not_a_heading():
    """„5 დღეზე მეტის გადატანა…“ მუხლი 4.7-ის ტექსტია, არა მუხლი 5."""
    assert match_heading(
        "5 დღეზე მეტის გადატანა დასაშვებია მხოლოდ მაშინ, როცა კომპანიამ უარყო."
    ) is None
    assert match_heading(
        "1 დეკემბრიდან 20 დეკემბრის ჩათვლით: წლიური აუდიტის დაგეგმვის პერიოდი;"
    ) is None


def test_numbering_must_move_forward():
    """მუხლი 4-ის შიგნით შემხვედრი „1 …“ სათაური ვერ იქნება."""
    from src.rag.chunker import _Sequence

    sequence = _Sequence()
    assert match_heading("4 ყოველწლიური შვებულება", sequence) is not None
    assert match_heading("4.1 ოდენობა", sequence) is not None
    assert match_heading("1 სხვა რამ", sequence) is None
    assert match_heading("4.2 ახალი თანამშრომლები", sequence) is not None


def test_article_numbers_are_complete_and_ordered():
    """შვებულების პოლიტიკის ყველა მუხლი ზუსტად უნდა ამოიცნოს."""
    meta = BY_FILENAME["Leave_and_Absence_Policy_v4.0.docx"]
    chunks = chunk_document(load_document(DOCUMENTS_DIR / meta.filename), meta)
    numbers = list(dict.fromkeys(c.article_no for c in chunks if c.article_no))

    for expected in ("1.4", "2.3", "4.4", "4.7", "5.1", "6.4", "7.2", "12.3"):
        assert expected in numbers
    assert numbers == sorted(numbers, key=lambda n: [int(p) for p in n.split(".")])


def test_chapter_headings_without_content_are_dropped():
    meta = BY_FILENAME["Leave_and_Absence_Policy_v4.0.docx"]
    chunks = chunk_document(load_document(DOCUMENTS_DIR / meta.filename), meta)
    assert not any(c.article_no == "3" for c in chunks)  # „3 შვებულების სახეები“


def test_all_faq_questions_are_indexed():
    meta = BY_FILENAME["Employee_FAQ_2025.docx"]
    chunks = chunk_document(load_document(DOCUMENTS_DIR / meta.filename), meta)
    numbers = {c.article_no for c in chunks}
    for expected in ("ა.1", "ა.9", "ბ.1", "გ.3", "დ.3", "ე.3"):
        assert expected in numbers
