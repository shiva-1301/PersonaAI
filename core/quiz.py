"""Quiz generation + grading.

A quiz is built from an allocation {topic_id: number_of_questions}. Phase 2 spreads
questions evenly over the chosen topics; adaptive mode (Phase 3) only changes the
allocation to favour weak topics.
"""

import json
import logging
import random
import re
from dataclasses import dataclass

from core import db, llm, rag, vectorstore

log = logging.getLogger(__name__)

QUIZ_SIZES = (5, 10, 15)
MAX_ATTEMPTS = 3  # LLM calls per quiz, including retries for malformed/missing questions
MAX_EXCERPTS = 14  # keeps the prompt within a local model's context window
LETTERS = "ABCD"
# Providers whose quizzes get an answer-key check. Small local models (llama3.1:8b) often
# write questions with a wrong key or two true options; Gemini's were all correct in
# testing, so it skips the extra call (and the quota it would use).
VERIFY_PROVIDERS = {"ollama"}

SYSTEM_PROMPT = """You write multiple-choice exam questions for a university student,
strictly from the numbered excerpts of the student's own notes."""

PROMPT = """Excerpts from the student's notes:

{excerpts}

Write exactly these questions, per topic:
{allocation}

Rules:
- Every question must be answerable from the excerpts alone. Do not use outside facts.
- Exactly 4 options, exactly one correct. Wrong options must be plausible: same type,
  similar length, about the same topic as the question (not borrowed from unrelated
  topics, which makes them easy to rule out). No "All of the above" / "None of the above".
- Each wrong option must be clearly wrong according to the excerpts; avoid options
  that are partly true.
- Mix difficulty: definitions, comparisons, and applying a concept (e.g. what a command
  or query does).
- Write questions the way an exam paper would: never mention "the notes", "the excerpts"
  or excerpt tags in the question or options.
- Don't ask the same thing twice.{avoid}
- "explanation": 1-2 sentences on why the correct answer is right, stated as fact
  (no "Excerpt S2 says...").
- "source": the tag of the excerpt the question is based on, e.g. "S3".

Return JSON ("answer" is the letter of the correct option):
{{"questions": [{{"topic": "T1", "question": "...", "options": ["...", "...", "...", "..."],
"answer": "B", "explanation": "...", "source": "S3"}}]}}"""

VERIFY_PROMPT = """Excerpts from a student's notes:

{excerpts}

Answer each multiple-choice question using only the excerpts. If no option is correct,
or more than one is, answer "X".

{questions}

Return JSON: {{"answers": [{{"n": 1, "answer": "B"}}]}}"""


class QuizError(RuntimeError):
    """The quiz couldn't be generated (no topics, no material, or the LLM kept failing)."""


@dataclass
class Question:
    topic_id: int
    topic: str
    question: str
    options: list[str]
    answer: int  # index into options
    explanation: str
    source: str | None = None  # "file, p. N"

    @property
    def correct_option(self) -> str:
        return self.options[self.answer]


@dataclass
class Result:
    score: int
    total: int
    correct: list[bool]
    attempt_id: int | None = None

    @property
    def percent(self) -> int:
        return round(100 * self.score / self.total) if self.total else 0


def even_allocation(topic_ids: list[int], n: int) -> dict[int, int]:
    """Spread n questions over topics as evenly as possible. With more topics than
    questions, a random subset of topics gets one question each."""
    if not topic_ids:
        return {}
    ids = list(topic_ids)
    random.shuffle(ids)
    base, extra = divmod(n, len(ids))
    allocation = {tid: base + (1 if i < extra else 0) for i, tid in enumerate(ids)}
    return {tid: k for tid, k in allocation.items() if k > 0}


def generate(user_id: int, allocation: dict[int, int]) -> list[Question]:
    """Generate questions for {topic_id: count}. May return slightly fewer than asked
    if the LLM keeps producing invalid questions; raises QuizError if it produces none."""
    topics = {t["id"]: t for t in db.list_topics(user_id) if t["id"] in allocation}
    allocation = {tid: n for tid, n in allocation.items() if tid in topics and n > 0}
    if not allocation:
        raise QuizError("No topics selected. Add topics to your documents first.")

    hits = _gather_excerpts(user_id, topics, allocation)
    if not hits:
        raise QuizError("Couldn't find any material for these topics in your notes.")

    questions: list[Question] = []
    needed = dict(allocation)
    for attempt in range(MAX_ATTEMPTS):
        prompt = build_prompt(hits, topics, needed, avoid=[q.question for q in questions])
        try:
            reply, model = llm.generate_with_model(
                prompt, system=SYSTEM_PROMPT, json_mode=True, temperature=0.7
            )
            new = parse_questions(reply, topics, hits, needed)
            if new and model.split(" / ")[0] in VERIFY_PROVIDERS:
                new = verify(new, hits)
        except llm.LLMError as exc:
            if questions:
                break
            raise QuizError(f"The AI service isn't responding: {exc}") from exc
        log.info("Quiz attempt %d: %d valid of %d needed", attempt + 1, len(new), sum(needed.values()))
        questions = _dedupe(questions + new)
        needed = _shortfall(allocation, questions)
        if not needed:
            break

    if not questions:
        raise QuizError("The AI couldn't produce valid questions. Please try again.")
    random.shuffle(questions)
    return questions


def verify(questions: list[Question], hits) -> list[Question]:
    """Have the model answer its own questions without seeing the key; keep only the
    questions where its answer matches. Catches wrong keys and ambiguous questions."""
    listing = "\n\n".join(
        f"{i}. {q.question}\n" + "\n".join(f"{LETTERS[j]}. {o}" for j, o in enumerate(q.options))
        for i, q in enumerate(questions, 1)
    )
    reply = llm.generate(
        VERIFY_PROMPT.format(excerpts=_excerpts(hits), questions=listing),
        json_mode=True,
        temperature=0,
    )
    try:
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.M).strip())
        answers = {int(a["n"]): str(a["answer"]).strip().upper()[:1] for a in data["answers"]}
    except (ValueError, KeyError, TypeError):
        log.warning("Quiz verification reply unreadable; keeping no questions: %r", reply[:200])
        return []
    kept = [q for i, q in enumerate(questions, 1) if answers.get(i) == LETTERS[q.answer]]
    log.info("Quiz verification kept %d of %d questions", len(kept), len(questions))
    return kept


def _excerpts(hits) -> str:
    return "\n\n".join(
        f"[S{i}] ({h.filename}{f', page {h.page}' if h.page else ''})\n{h.text}"
        for i, h in enumerate(hits, 1)
    )


def _gather_excerpts(user_id: int, topics: dict, allocation: dict[int, int]) -> list[vectorstore.Hit]:
    """The best excerpts for each topic (more for topics with more questions), deduplicated."""
    per_topic = max(1, MAX_EXCERPTS // len(allocation))
    seen, hits = set(), []
    for tid, count in allocation.items():
        topic = topics[tid]
        k = min(max(per_topic, 1), max(1, count + 1))
        doc_ids = [topic["document_id"]] if topic["document_id"] else None
        for hit in rag.retrieve(user_id, topic["name"], document_ids=doc_ids, k=k):
            key = (hit.document_id, hit.text[:80])
            if key not in seen:
                seen.add(key)
                hits.append(hit)
    return hits[:MAX_EXCERPTS]


def build_prompt(hits, topics: dict, needed: dict[int, int], avoid: list[str] = ()) -> str:
    excerpts = _excerpts(hits)
    tags = _topic_tags(needed)
    allocation = "\n".join(
        f'{tag}: "{topics[tid]["name"]}" - {needed[tid]} question{"s" if needed[tid] > 1 else ""}'
        for tag, tid in tags.items()
    )
    avoid_text = ""
    if avoid:
        avoid_text = "\n- These were already asked; write different ones:\n" + "\n".join(
            f"  * {q}" for q in avoid
        )
    return PROMPT.format(excerpts=excerpts, allocation=allocation, avoid=avoid_text)


def _topic_tags(needed: dict[int, int]) -> dict[str, int]:
    return {f"T{i}": tid for i, tid in enumerate(needed, 1)}


def parse_questions(reply: str, topics: dict, hits, needed: dict[int, int]) -> list[Question]:
    """Validate the LLM's JSON; silently drop malformed questions."""
    try:
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.M).strip())
    except json.JSONDecodeError:
        log.warning("Quiz reply was not valid JSON: %r", reply[:200])
        return []
    items = data.get("questions", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    tags = _topic_tags(needed)
    questions = []
    for item in items:
        q = _validate(item, tags, topics, hits)
        if q:
            questions.append(q)
    return questions


def _validate(item, tags: dict[str, int], topics: dict, hits) -> Question | None:
    if not isinstance(item, dict):
        return None
    text = str(item.get("question", "")).strip()
    options = item.get("options")
    if not text or not isinstance(options, list) or len(options) != 4:
        return None
    # Strip "A) " / "B. " prefixes the model sometimes adds.
    options = [re.sub(r"^\s*[A-Da-d][).:]\s+", "", str(o)).strip() for o in options]
    if any(not o for o in options) or len({o.lower() for o in options}) != 4:
        return None
    if any(o.lower() in {"all of the above", "none of the above"} for o in options):
        return None

    answer = _answer_index(item.get("answer"), options)
    if answer is None:
        return None

    tid = tags.get(str(item.get("topic", "")).strip().upper())
    if tid is None:
        return None

    source = None
    match = re.search(r"\d+", str(item.get("source", "")))
    if match and 1 <= int(match.group()) <= len(hits):
        hit = hits[int(match.group()) - 1]
        source = f"{hit.filename}, p. {hit.page}" if hit.page else hit.filename

    # Shuffle so the correct answer isn't always where the model likes to put it.
    correct = options[answer]
    random.shuffle(options)
    return Question(
        topic_id=tid,
        topic=topics[tid]["name"],
        question=text,
        options=options,
        answer=options.index(correct),
        explanation=str(item.get("explanation", "")).strip(),
        source=source,
    )


def _answer_index(answer, options: list[str]) -> int | None:
    """Accept "B", "b)", or the full option text. Numbers are rejected: models mix
    0-based and 1-based indexes, so 2 could mean B or C."""
    if not isinstance(answer, str):
        return None
    text = answer.strip()
    if re.fullmatch(r"[A-Da-d][).:]?", text):
        return LETTERS.index(text[0].upper())
    for i, option in enumerate(options):
        if text.lower() == option.lower():
            return i
    return None


def _dedupe(questions: list[Question]) -> list[Question]:
    seen, unique = set(), []
    for q in questions:
        key = re.sub(r"\W+", " ", q.question.lower()).strip()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


def _shortfall(allocation: dict[int, int], questions: list[Question]) -> dict[int, int]:
    """Trim surplus questions per topic in place and return what's still missing."""
    have: dict[int, int] = {}
    kept = []
    for q in questions:
        if have.get(q.topic_id, 0) < allocation.get(q.topic_id, 0):
            have[q.topic_id] = have.get(q.topic_id, 0) + 1
            kept.append(q)
    questions[:] = kept
    return {tid: n - have.get(tid, 0) for tid, n in allocation.items() if n > have.get(tid, 0)}


def grade(questions: list[Question], chosen: list[int | None]) -> Result:
    correct = [c is not None and c == q.answer for q, c in zip(questions, chosen)]
    return Result(score=sum(correct), total=len(questions), correct=correct)


def submit(user_id: int, questions: list[Question], chosen: list[int | None]) -> Result:
    """Grade the quiz and save the attempt and every answer."""
    result = grade(questions, chosen)
    rows = [
        (
            q.topic_id,
            q.question,
            q.options[c] if c is not None else None,
            q.correct_option,
            ok,
        )
        for q, c, ok in zip(questions, chosen, result.correct)
    ]
    result.attempt_id = db.save_quiz_attempt(user_id, result.score, result.total, rows)
    return result
