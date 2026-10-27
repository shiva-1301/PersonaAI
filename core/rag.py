"""Question -> retrieve -> answer with citations."""

import json
import re
from dataclasses import dataclass, field

from core import documents, llm, vectorstore

# Retrieval is two-stage: embedding search finds CANDIDATES chunks quickly, then a
# cross-encoder reads each (question, chunk) pair and reranks them. Embeddings only
# know a chunk is "about Pig"; the cross-encoder can tell which chunk answers
# "What is Pig?". On the Big Data notes this moved the defining chunk from 8th to 1st.
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CANDIDATES = 20
TOP_K = 5
RETRIEVAL = "embedding -> cross-encoder"  # recorded with evaluation results
# Reranker score below which a chunk is treated as unrelated. Calibrated on the Big Data
# notes: on-syllabus questions scored -2.3 to 8.6 for their best chunk, unrelated ones
# (linked lists, HDFS replication) -9.4 to -4.7. Near-domain off-syllabus questions can
# score higher, so the LLM is also told to say NOT_FOUND when the excerpts lack the answer.
MIN_SCORE = -5.0
NOT_FOUND = "NOT_FOUND"
NOT_FOUND_MESSAGE = (
    "I couldn't find this in your notes. Try rephrasing, or upload the material that covers it."
)

SYSTEM_PROMPT = f"""You are PersonaAI, a study assistant for a university student.
Answer the question using ONLY the numbered excerpts from the student's own notes.

Rules:
- Use only facts stated in the excerpts. Do not add outside knowledge.
- Cite the excerpts you used inline with their tags, like [S1] or [S2][S4], right after the
  sentence they support. Only use these [S#] tags for citations, never the notes' own numbering.
- If the excerpts answer only part of the question, answer that part and then say plainly
  which part the notes don't cover. Do not fill the gap from outside knowledge.
- If the excerpts answer none of it, reply with exactly {NOT_FOUND} and nothing else.
- Write the way a good exam answer reads: a one-line definition or direct answer first,
  then key points as bullets. Include a short example or syntax if the excerpts give one.
- Keep it concise."""


@dataclass
class Source:
    number: int  # n in the [Sn] tag used in the answer
    filename: str
    page: int | None
    excerpt: str

    @property
    def label(self) -> str:
        return documents.location(self.filename, self.page)


@dataclass
class Answer:
    text: str
    found: bool
    sources: list[Source] = field(default_factory=list)
    model: str | None = None  # which LLM wrote the answer; None if no LLM was called


def build_prompt(question: str, hits: list[vectorstore.Hit]) -> str:
    blocks = []
    for i, hit in enumerate(hits, 1):
        blocks.append(f"[S{i}] ({documents.location(hit.filename, hit.page)})\n{hit.text}")
    return "Excerpts from the student's notes:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


def parse_answer(reply: str, hits: list[vectorstore.Hit]) -> Answer:
    text = reply.strip()
    if not text or text.upper().startswith(NOT_FOUND) or text.upper().rstrip(".") == NOT_FOUND:
        return Answer(NOT_FOUND_MESSAGE, found=False)

    cited = []
    for n in re.findall(r"\[S(\d+)\]", text, flags=re.IGNORECASE):
        n = int(n)
        if 1 <= n <= len(hits) and n not in cited:
            cited.append(n)
    # If the model forgot to cite, show everything it was given rather than nothing.
    numbers = sorted(cited) or list(range(1, len(hits) + 1))
    sources = [
        Source(n, hits[n - 1].filename, hits[n - 1].page, hits[n - 1].text) for n in numbers
    ]
    return Answer(text, found=True, sources=sources)


_reranker = None


def _cross_encoder():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(RERANK_MODEL)
    return _reranker


def retrieve(
    user_id: int, question: str, document_ids: list[int] | None = None, k: int = TOP_K
) -> list[vectorstore.Hit]:
    """Best k relevant chunks for the question, best first (empty if none are relevant)."""
    candidates = vectorstore.search(user_id, question, k=CANDIDATES, document_ids=document_ids)
    if not candidates:
        return []
    scores = _cross_encoder().predict([(question, h.text) for h in candidates])
    for hit, score in zip(candidates, scores):
        hit.score = float(score)
    ranked = sorted(candidates, key=lambda h: h.score, reverse=True)
    return [h for h in ranked if h.score >= MIN_SCORE][:k]


SPLIT_PROMPT = """A student asked: "{question}"

If this asks about more than one thing (e.g. two concepts, or two questions joined by "and"),
split it into standalone questions, each repeating the shared context (e.g. "in a CNN").
If it asks one thing, return it unchanged as the only item. At most {n} questions.

Return JSON: {{"questions": ["...", "..."]}}"""
SPLIT_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions"],
    "additionalProperties": False,
}
MAX_PARTS = 3
MAX_EXCERPTS_MULTI = 8  # excerpts for a multi-part question (TOP_K for a single one)
# Only these questions are sent to the splitter; the rest skip the extra LLM call.
_MAYBE_MULTI = re.compile(r"\band\b|;|\?.*\?", re.IGNORECASE)


def sub_questions(question: str) -> list[str]:
    """The separate questions inside a multi-part question ("What does YARN's Resource
    Manager do, and what does a pooling layer do?"); [question] if it asks one thing.
    Searching once for the whole question lets one part take every excerpt slot."""
    if not _MAYBE_MULTI.search(question):
        return [question]
    try:
        reply = llm.generate(SPLIT_PROMPT.format(question=question, n=MAX_PARTS), json_mode=True,
                             schema=SPLIT_SCHEMA, temperature=0)
        parts = [p.strip() for p in json.loads(reply)["questions"] if isinstance(p, str) and p.strip()]
    except (llm.LLMError, ValueError, KeyError, TypeError):
        return [question]
    return parts[:MAX_PARTS] if len(parts) > 1 else [question]


def retrieve_for_answer(
    user_id: int, question: str, document_ids: list[int] | None = None
) -> list[vectorstore.Hit]:
    """retrieve(), but a multi-part question gets the best excerpts for each part, taken in
    turn (part 1's best, part 2's best, ...) so every part is represented."""
    parts = sub_questions(question)
    if len(parts) == 1:
        return retrieve(user_id, question, document_ids)
    ranked = [retrieve(user_id, part, document_ids) for part in parts]
    merged, seen = [], set()
    for i in range(TOP_K):
        for hits in ranked:
            if i < len(hits) and (hits[i].document_id, hits[i].text[:80]) not in seen:
                seen.add((hits[i].document_id, hits[i].text[:80]))
                merged.append(hits[i])
    return merged[:MAX_EXCERPTS_MULTI]


def warm_up() -> None:
    """Load the embedding and reranking models (~30s the first time)."""
    vectorstore.embed(["warm up"])
    _cross_encoder()


def answer(user_id: int, question: str, document_ids: list[int] | None = None) -> Answer:
    question = question.strip()
    if not question:
        raise ValueError("Question is empty.")
    hits = retrieve_for_answer(user_id, question, document_ids)
    if not hits:
        return Answer(NOT_FOUND_MESSAGE, found=False)
    reply, model = llm.generate_with_model(build_prompt(question, hits), system=SYSTEM_PROMPT)
    result = parse_answer(reply, hits)
    result.model = model
    return result
