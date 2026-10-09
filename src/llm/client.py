"""LLM კლიენტი ორი რეჟიმით: `mock` და `anthropic`.

`mock` რეჟიმი გასაღების გარეშე მუშაობს და ნამდვილად ასრულებს საქმეს:
განზრახვას საკვანძო სიტყვებით ცნობს, პასუხს კი მოძიებული ამონარიდებიდან
ექსტრაქტულად აწყობს წყაროს მითითებით. ასე პროექტი შემმოწმებელთან
გასაღების გარეშეც სრულად ეშვება, ხოლო გასაღების დამატებისას იგივე კოდი
რეალურ მოდელს იყენებს.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_PROVIDER
from src.llm.prompts import INTENT_SYSTEM, RAG_SYSTEM, rag_user_prompt

NOT_FOUND_MESSAGE = (
    "ამ საკითხზე მოწოდებულ დოკუმენტებში პასუხი ვერ ვიპოვე. "
    "გთხოვთ, მიმართოთ ადამიანური რესურსების სამსახურს."
)


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Intent:
    intent: str
    leave_type: str | None = None
    date_text: str | None = None
    reason: str | None = None


# mock რეჟიმის წესები

_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SICK", ("ავად", "ავადმყოფ", "გავცივდ", "გაციებ", "ექიმ", "ოპერაცი",
              "ბიულეტენ", "ცუდად ვარ", "სიცხ")),
    ("BEREAVEMENT", ("გარდაიცვალ", "გარდამეცვალ", "დაკრძალვ", "გლოვ",
                     "სამძიმარ")),
    ("STUDY", ("გამოცდ", "სასწავლო", "სერტიფიც", "acca", "cima", "cfa",
               "cisa", "ემზადებ")),
    ("PARENTAL", ("დედობ", "მამობ", "დეკრეტ", "ბავშვის მოვლ", "მშობლის შვებ")),
    ("UNPAID", ("უხელფასო", "ანაზღაურების გარეშე", "ხელფასის გარეშე")),
    ("ANNUAL", ("შვებულებ", "დასვენებ", "დავისვენებ", "ვისვენებ", "შვებულება",
                "მოგზაურ", "ანაზღაურებად")),
)

_BALANCE_KEYWORDS = ("ნაშთ", "ბალანს", "რამდენი დღე დამრჩ", "დამრჩა",
                     "რამდენი მაქვს", "დარჩენილ")
_QUESTION_KEYWORDS = ("რამდენი", "როდის", "როგორ", "რა ვადა", "შემიძლია",
                      "მეკუთვნის", "რას ნიშნავს", "ვინ ამტკიცებს", "სად")
_CREATE_KEYWORDS = ("მინდა", "მსურს", "ვითხოვ", "ავიღებ", "დავისვენებ",
                    "გავფორმებ", "ავად ვარ", "მოვითხოვ", "დამჭირდა")

_LIST_KEYWORDS = ("მანახე", "მაჩვენე", "ჩამომითვალე", "სია", "სიას",
                  "რა მოთხოვნები", "ჩემი მოთხოვნ", "მოთხოვნები მაქვს",
                  "გაგზავნილი", "განხილვაში")

_GREETINGS = ("გამარჯობა", "სალამი", "მადლობა", "გმადლობ", "ნახვამდის", "კი",
              "დიახ", "არა")


def detect_leave_type(text: str) -> str | None:
    """შვებულების სახე ტექსტიდან — ექვსივე სახე უნდა ამოიცნოს."""
    lowered = text.lower()
    for code, keywords in _TYPE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return code
    return None


def _mock_intent(text: str) -> Intent:
    lowered = text.lower().strip()
    leave_type = detect_leave_type(lowered)

    if any(word in lowered for word in _BALANCE_KEYWORDS):
        return Intent("balance", leave_type)

    asks_question = any(word in lowered for word in _QUESTION_KEYWORDS)
    wants_action = any(word in lowered for word in _CREATE_KEYWORDS)

    # „მანახე მოთხოვნები“ ნახვაა და არა შექმნა — შექმნის ზმნა უპირატესია.
    if any(word in lowered for word in _LIST_KEYWORDS) and not wants_action:
        return Intent("list_requests", leave_type)

    if wants_action and not asks_question:
        return Intent("create_request", leave_type, date_text=text)
    if asks_question:
        return Intent("policy_question", leave_type)
    if leave_type:
        return Intent("create_request", leave_type, date_text=text)
    if lowered in _GREETINGS or len(lowered) < 4:
        return Intent("other")
    return Intent("policy_question", leave_type)


MOCK_EXCERPTS = 3


def _mock_answer(context: str) -> str:
    """ექსტრაქტული პასუხი — ყველაზე რელევანტური ამონარიდები წყაროებით.

    mock-ს შინაარსის შეჯამება არ შეუძლია, ამიტომ ერთი ფრაგმენტის ნაცვლად
    საუკეთესო სამს აჩვენებს: BM25-ის პირველი ადგილი ყოველთვის სწორი მუხლი
    არ არის და ერთი ამონარიდი მომხმარებელს არასწორ პასუხთან მიიყვანდა.
    """
    if not context.strip():
        return NOT_FOUND_MESSAGE

    blocks = context.split("\n\n---\n\n")
    citations = [
        re.sub(r"^\[\d+\]\s*", "", block.splitlines()[0]) for block in blocks
    ]

    lines = [
        "(mock რეჟიმი — ქვემოთ დოკუმენტების პირდაპირი ამონარიდებია, "
        "რეალური LLM-ის შეჯამების გარეშე)",
    ]

    for citation, block in zip(citations[:MOCK_EXCERPTS], blocks[:MOCK_EXCERPTS]):
        body = "\n".join(line for line in block.splitlines()[2:] if line.strip())
        lines += ["", f"— {citation}", body]

    if len(citations) > MOCK_EXCERPTS:
        lines += ["", "სხვა შესაძლო წყაროები:"]
        lines += [f"  • {c}" for c in citations[MOCK_EXCERPTS:]]

    reference = [c for c in citations if "კითხვა" in c]
    if reference and len(citations) > len(reference):
        lines += [
            "",
            "გაითვალისწინეთ: ხშირად დასმული კითხვების დოკუმენტი საცნობარო "
            "მასალაა და შეიძლება მოძველებული იყოს — წინააღმდეგობისას "
            "მოქმედებს პოლიტიკა (შვებულებისა და გაცდენის პოლიტიკა, მუხლი 1.4).",
        ]
    return "\n".join(lines)




class LLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        self.provider = (provider or LLM_PROVIDER).lower()
        self.model = model or ANTHROPIC_MODEL
        self._client: Any = None

        if self.provider == "anthropic" and not ANTHROPIC_API_KEY:
            raise LLMError(
                "LLM_PROVIDER=anthropic, მაგრამ ANTHROPIC_API_KEY დაყენებული "
                "არ არის. გამოიყენეთ LLM_PROVIDER=mock ან შეავსეთ გასაღები."
            )

    @property
    def is_mock(self) -> bool:
        return self.provider != "anthropic"

    def _anthropic(self) -> Any:
        if self._client is None:
            import anthropic  # ლოკალური იმპორტი: mock რეჟიმს არ სჭირდება

            self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        return self._client

    def _complete(self, system: str, user: str, *, max_tokens: int = 2000) -> str:
        import anthropic

        try:
            response = self._anthropic().messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIStatusError as exc:
            raise LLMError(f"LLM-ის შეცდომა ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("LLM-თან კავშირი ვერ დამყარდა.") from exc

        if response.stop_reason == "refusal":
            raise LLMError("მოდელმა პასუხზე უარი თქვა.")

        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()


    def classify(self, text: str) -> Intent:
        """განზრახვა და სლოტები თანამშრომლის შეტყობინებიდან."""
        if self.is_mock:
            return _mock_intent(text)

        try:
            raw = self._complete(INTENT_SYSTEM, text, max_tokens=400)
            payload = json.loads(_extract_json(raw))
        except (LLMError, json.JSONDecodeError, ValueError):
            return _mock_intent(text)  # საიმედო fallback

        intent = payload.get("intent")
        if intent not in {"policy_question", "balance", "create_request",
                          "list_requests", "other"}:
            return _mock_intent(text)

        return Intent(
            intent=intent,
            leave_type=payload.get("leave_type") or detect_leave_type(text),
            date_text=payload.get("date_text") or text,
            reason=payload.get("reason"),
        )

    def answer_policy_question(self, question: str, context: str) -> str:
        """პასუხი მხოლოდ მოძიებულ ამონარიდებზე დაყრდნობით."""
        if not context.strip():
            return NOT_FOUND_MESSAGE
        if self.is_mock:
            return _mock_answer(context)
        return self._complete(RAG_SYSTEM, rag_user_prompt(question, context))


def _extract_json(text: str) -> str:
    """პასუხიდან JSON ობიექტს გამოყოფს, თუ ტექსტში გახვეულია."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("JSON ვერ მოიძებნა")
    return text[start : end + 1]
