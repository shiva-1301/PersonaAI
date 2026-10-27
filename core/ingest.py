"""Upload pipeline: save file -> extract -> chunk -> embed -> extract topics."""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core import config, db, llm, vectorstore
from core.documents import Page, chunk_pages, extract_pages

log = logging.getLogger(__name__)

# Characters of document text sent to the LLM for topic extraction (~6k tokens).
TOPIC_TEXT_LIMIT = 24_000

TOPIC_PROMPT = """Below is a student's study material. List the main syllabus topics it covers,
the way they would appear in a course syllabus or exam paper.

- 5 to 15 topics, in the order they appear.
- Each topic is a short name (2-6 words), e.g. "Pig Latin data types", "Hive partitioning".
- Specific enough to quiz on, but not individual facts.

Return JSON: {{"topics": ["...", "..."]}}

Material:
{text}"""


TOPICS_SCHEMA = {
    "type": "object",
    "properties": {"topics": {"type": "array", "items": {"type": "string"}}},
    "required": ["topics"],
    "additionalProperties": False,
}


@dataclass
class IngestResult:
    document_id: int
    filename: str
    pages: int
    chunks: int
    topics: list[str] = field(default_factory=list)
    warning: str | None = None


def ingest(
    user_id: int, filename: str, data: bytes, subject: str | None = None, *,
    cohort_id: int | None = None, subject_id: int | None = None, unit: str | None = None,
) -> IngestResult:
    """Add a document: a student's personal notes, or (with cohort_id) course notes the
    admin shares with a cohort. Re-uploading a file with the same name replaces its
    text but keeps its topics, so their quiz history survives.
    Raises documents.DocumentError for unreadable files."""
    filename = Path(filename).name
    pages = extract_pages(filename, data)
    chunks = chunk_pages(pages)
    page_count = len(pages) if pages[0].number else 0

    path = _upload_path(user_id, filename, cohort_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    existing = db.find_document(user_id, filename, cohort_id=cohort_id)
    if existing:
        document_id = existing["id"]
        vectorstore.delete_document(document_id)
        db.update_document(document_id, subject, page_count, subject_id=subject_id, unit=unit)
        vectorstore.add_chunks(user_id, document_id, filename, chunks, cohort_id)
        topics = [t["name"] for t in db.list_topics(user_id, document_id)]
        if topics:
            return IngestResult(document_id, filename, len(pages), len(chunks), topics)
    else:
        document_id = db.add_document(
            user_id, filename, subject, page_count, cohort_id=cohort_id, subject_id=subject_id, unit=unit
        )
        try:
            vectorstore.add_chunks(user_id, document_id, filename, chunks, cohort_id)
        except Exception:
            db.delete_document(document_id)
            path.unlink(missing_ok=True)
            raise

    result = IngestResult(document_id, filename, len(pages), len(chunks))
    try:
        result.topics = extract_topics(pages)
        db.set_topics(user_id, document_id, result.topics)
    except Exception as exc:
        log.warning("Topic extraction failed for %s: %s", filename, exc)
        result.warning = "Couldn't extract topics automatically. You can add them by hand."
    return result


def remove(user_id: int, document_id: int) -> None:
    """Delete a document the user owns (students can't delete shared course notes)."""
    doc = db.get_document(document_id)
    if doc is None or doc["user_id"] != user_id:
        return
    vectorstore.delete_document(document_id)
    db.delete_document(document_id)
    _upload_path(user_id, doc["filename"], doc["cohort_id"]).unlink(missing_ok=True)


def extract_topics(pages: list[Page]) -> list[str]:
    text = _sample_text(pages, TOPIC_TEXT_LIMIT)
    reply = llm.generate(TOPIC_PROMPT.format(text=text), json_mode=True, schema=TOPICS_SCHEMA)
    topics = parse_topics(reply)
    if not topics:
        raise ValueError(f"No topics in LLM reply: {reply[:200]!r}")
    return topics


def parse_topics(reply: str) -> list[str]:
    """Accept {"topics": [...]}, a bare list, or either wrapped in ```json fences."""
    reply = re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.MULTILINE).strip()
    data = json.loads(reply)
    if isinstance(data, dict):
        data = data.get("topics", [])
    if not isinstance(data, list):
        return []
    topics = []
    for item in data:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            topics.append(" ".join(name.split())[:80])
    return topics[:15]


def _sample_text(pages: list[Page], limit: int) -> str:
    """Whole text if it fits; otherwise an equal slice of every page, so topics from
    the end of a long document aren't cut off."""
    full = "\n\n".join(p.text for p in pages)
    if len(full) <= limit:
        return full
    per_page = max(200, limit // len(pages))
    return "\n\n".join(p.text[:per_page] for p in pages)[:limit]


def _upload_path(user_id: int, filename: str, cohort_id: int | None = None) -> Path:
    folder = f"cohort_{cohort_id}" if cohort_id else str(user_id)
    return config.UPLOADS_DIR / folder / filename
