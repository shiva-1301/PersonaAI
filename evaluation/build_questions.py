"""Build evaluation/questions.csv from the "BD MID 2 SHORTS" exam Q&A PDF.

The PDF has 30 short questions with model answers for each of Unit III and Unit IV.
They are split into two sets of 30 that both cover the whole syllabus:
  * questions.csv          odd-numbered questions: the DEVELOPMENT set, used to find and
                           fix problems in the pipeline;
  * questions_holdout.csv  even-numbered questions: the HELD-OUT set, run only on the
                           final pipeline, so its score isn't inflated by tuning.
The evaluation answers them using ONLY the Unit III/IV notes, never this PDF, so the
"with notes" answers can't simply copy the reference answers.

Usage:  python -m evaluation.build_questions [path/to/shorts.pdf]
"""

import csv
import re
import sys
from pathlib import Path

from core.documents import extract_pages

DEFAULT_PDF = Path("data/uploads/BD MID 2 SHORTS.pdf")
OUT = Path(__file__).with_name("questions.csv")
HOLDOUT = Path(__file__).with_name("questions_holdout.csv")
QUESTION_START = re.compile(
    r"^(?:what|how|why|which|when|where|who|explain|define|differentiate|compare|list|"
    r"describe|name|give|write|state|mention)\b",
    re.IGNORECASE,
)


def parse(text: str) -> list[dict]:
    text = text.replace("IgniteXT", "\n")
    units = re.split(r"Big Data Unit\W+(III|IV)\b[^\n]*", text)
    questions = []
    # re.split with a group gives [before, "III", body, "IV", body]
    for unit, body in zip(units[1::2], units[2::2]):
        lines = [ln.strip() for ln in body.splitlines()]
        expected, current = 1, None
        for line in lines:
            m = re.match(rf"^{expected}\.\s+(.+)$", line)
            if m and (m.group(1).endswith("?") or QUESTION_START.match(m.group(1))):
                current = {"unit": unit, "number": expected, "question": m.group(1), "answer": []}
                questions.append(current)
                expected += 1
            elif current is not None and line and not _is_heading(line):
                current["answer"].append(line)
    for q in questions:
        q["answer"] = _clean_answer(q["answer"])
    return questions


def _is_heading(line: str) -> bool:
    """Section titles like "PART A — APACHE PIG" or "HIVE TABLES AND STORAGE"."""
    letters = re.sub(r"[^A-Za-z]", "", line)
    return line == "Answer:" or (len(letters) > 3 and letters.isupper() and not line[0].isdigit())


def _clean_answer(lines: list[str]) -> str:
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*Example:\s*", " Example: ", text)
    return text


def main() -> None:
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    pages = extract_pages(pdf.name, pdf.read_bytes())
    questions = parse("\n".join(p.text for p in pages))
    by_unit = {u: [q for q in questions if q["unit"] == u] for u in ("III", "IV")}
    print({u: len(qs) for u, qs in by_unit.items()}, "questions found")
    dev = [q for qs in by_unit.values() for q in qs[::2]]
    holdout = [q for qs in by_unit.values() for q in qs[1::2]]
    write(OUT, dev, start=1, pdf=pdf)
    write(HOLDOUT, holdout, start=len(dev) + 1, pdf=pdf)


def write(path: Path, questions: list[dict], start: int, pdf: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "unit", "question", "reference_answer", "source"])
        for i, q in enumerate(questions, start):
            writer.writerow([i, q["unit"], q["question"], q["answer"], f"{pdf.name} Q{q['number']}"])
    print(f"Wrote {len(questions)} questions to {path}")


if __name__ == "__main__":
    main()
