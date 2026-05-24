"""Contact cleanup — reads a vCard (.vcf) file and removes contacts without a phone number."""
from __future__ import annotations

import re
import sys
from pathlib import Path


_PHONE_TAG = re.compile(r"^TEL[;:]", re.IGNORECASE)


def _split_vcards(text: str) -> list[str]:
    cards: list[str] = []
    current: list[str] = []
    for line in text.splitlines(keepends=True):
        current.append(line)
        if line.strip().upper() == "END:VCARD":
            cards.append("".join(current))
            current = []
    return cards


def _has_phone(vcard: str) -> bool:
    return any(_PHONE_TAG.match(line) for line in vcard.splitlines())


def _extract_name(vcard: str) -> str:
    for line in vcard.splitlines():
        if line.upper().startswith("FN:"):
            return line[3:].strip()
    return "(ללא שם)"


def clean_contacts(input_path: Path, output_path: Path) -> tuple[int, int]:
    """Remove contacts without a phone number from a vCard file.

    Returns (total, removed) counts.
    """
    text = input_path.read_text(encoding="utf-8", errors="replace")
    cards = _split_vcards(text)

    kept: list[str] = []
    removed_names: list[str] = []

    for card in cards:
        if _has_phone(card):
            kept.append(card)
        else:
            removed_names.append(_extract_name(card))

    output_path.write_text("".join(kept), encoding="utf-8")

    if removed_names:
        print(f"\nאנשי קשר שהוסרו ({len(removed_names)}):")
        for name in removed_names:
            print(f"  - {name}")

    print(f"\nסיכום: {len(cards)} אנשי קשר סה\"כ, הוסרו {len(removed_names)}, נשארו {len(kept)}")
    return len(cards), len(removed_names)


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("שימוש: python -m career_agent.contacts.cleaner <קובץ_קלט.vcf> [קובץ_פלט.vcf]")
        sys.exit(1)

    input_path = Path(args[0])
    if not input_path.exists():
        print(f"שגיאה: הקובץ '{input_path}' לא נמצא")
        sys.exit(1)

    output_path = Path(args[1]) if len(args) > 1 else input_path.with_stem(input_path.stem + "_cleaned")
    clean_contacts(input_path, output_path)
    print(f"הקובץ הנקי נשמר ב: {output_path}")


if __name__ == "__main__":
    main()
