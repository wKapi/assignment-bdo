"""დოკუმენტების კატალოგი — მეტამონაცემები და უპირატესობის დონეები.

დონეები თავად დოკუმენტებშია განსაზღვრული და აქ მხოლოდ კოდში
გადმოტანილია:

* შვებულების პოლიტიკა, მუხლი 1.4 — „თუ ეს პოლიტიკა ეწინააღმდეგება
  თანამშრომლის სახელმძღვანელოს, ხშირად დასმული კითხვების დოკუმენტს ან
  სხვა ზოგად მასალას, მოქმედებს ეს პოლიტიკა“.
* სახელმძღვანელო, მუხლი 1.2 — „თუ ამ სახელმძღვანელოსა და სპეციალურ
  პოლიტიკას შორის განსხვავებაა, მოქმედებს სპეციალური პოლიტიკა“.
* დისტანციური მუშაობის პოლიტიკა, მუხლი 1.3 — „ეს ვერსია ცვლის
  დისტანციური მუშაობის წინა წესებს, მათ შორის თანამშრომლის
  სახელმძღვანელოს მე-6 მუხლს“.
* FAQ-ის სტატუსი — „საცნობარო მასალა; შეიძლება შეიცავდეს მოძველებულ
  ინფორმაციას“.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# უპირატესობის დონეები (რაც მეტია, მით უფრო სავალდებულოა წყარო)
TIER_POLICY = 3  # მოქმედი სპეციალური პოლიტიკა
TIER_HANDBOOK = 2  # თანამშრომლის სახელმძღვანელო — ზოგადი მიმოხილვა
TIER_REFERENCE = 1  # საცნობარო მასალა (FAQ)

TIER_LABELS = {
    TIER_POLICY: "მოქმედი პოლიტიკა",
    TIER_HANDBOOK: "სახელმძღვანელო (ზოგადი მიმოხილვა)",
    TIER_REFERENCE: "საცნობარო მასალა, შეიძლება მოძველებული იყოს",
}


@dataclass(frozen=True)
class DocumentMeta:
    filename: str
    title: str
    code: str
    version: str
    effective_date: str
    status: str
    tier: int
    superseded_sections: dict[str, str] = field(default_factory=dict)
    """თავის ნომერი → დოკუმენტი, რომელმაც ის ჩაანაცვლა."""

    @property
    def citation(self) -> str:
        """ციტირების ერთგვაროვანი ფორმა: „დასახელება v4.0“."""
        return f"{self.title} v{self.version}"

    @property
    def tier_label(self) -> str:
        return TIER_LABELS[self.tier]

    def section_superseded_by(self, article_no: str | None) -> str | None:
        """თუ ეს მუხლი სხვა დოკუმენტმა ჩაანაცვლა, აბრუნებს მის სახელს."""
        if not article_no:
            return None
        chapter = article_no.split(".")[0]
        return self.superseded_sections.get(chapter)


CATALOG: tuple[DocumentMeta, ...] = (
    DocumentMeta(
        filename="Leave_and_Absence_Policy_v4.0.docx",
        title="შვებულებისა და გაცდენის პოლიტიკა",
        code="HR-POL-02",
        version="4.0",
        effective_date="2026-01-01",
        status="მოქმედი",
        tier=TIER_POLICY,
    ),
    DocumentMeta(
        filename="Remote_and_Hybrid_Work_Policy_v2.0.pdf",
        title="დისტანციური და ჰიბრიდული მუშაობის პოლიტიკა",
        code="HR-POL-05",
        version="2.0",
        effective_date="2026-09-01",
        status="მოქმედი",
        tier=TIER_POLICY,
    ),
    DocumentMeta(
        filename="Information_Security_Policy_v3.2.pdf",
        title="ინფორმაციული უსაფრთხოებისა და IT რესურსების გამოყენების პოლიტიკა",
        code="SEC-POL-01",
        version="3.2",
        effective_date="2026-03-01",
        status="მოქმედი",
        tier=TIER_POLICY,
    ),
    DocumentMeta(
        filename="Travel_and_Expense_Policy_v2.3.pdf",
        title="მივლინებისა და ხარჯების ანაზღაურების პოლიტიკა",
        code="FIN-POL-03",
        version="2.3",
        effective_date="2026-04-01",
        status="მოქმედი",
        tier=TIER_POLICY,
    ),
    DocumentMeta(
        filename="Learning_and_Development_Policy_v1.2.pdf",
        title="სწავლისა და პროფესიული განვითარების პოლიტიკა",
        code="HR-POL-07",
        version="1.2",
        effective_date="2026-02-01",
        status="მოქმედი",
        tier=TIER_POLICY,
    ),
    DocumentMeta(
        filename="Employee_Handbook_v3.1.docx",
        title="თანამშრომლის სახელმძღვანელო",
        code="HR-HB-01",
        version="3.1",
        effective_date="2025-02-01",
        status="მოქმედი (ზოგადი მიმოხილვა)",
        tier=TIER_HANDBOOK,
        superseded_sections={
            "5": "შვებულებისა და გაცდენის პოლიტიკა v4.0",
            "6": "დისტანციური და ჰიბრიდული მუშაობის პოლიტიკა v2.0",
        },
    ),
    DocumentMeta(
        filename="Employee_FAQ_2025.docx",
        title="ხშირად დასმული კითხვები თანამშრომლებისთვის",
        code="HR-FAQ-01",
        version="1.4",
        effective_date="2025-11-01",
        status="საცნობარო მასალა; შეიძლება შეიცავდეს მოძველებულ ინფორმაციას",
        tier=TIER_REFERENCE,
    ),
)

BY_FILENAME: dict[str, DocumentMeta] = {d.filename: d for d in CATALOG}
