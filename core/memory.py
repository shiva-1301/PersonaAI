"""Topic scores and weak-topic detection.

A topic's accuracy is measured over the student's most recent answers on it (not
all-time), so improving actually moves a topic out of "weak". Scores are rebuilt from
quiz_answers after every quiz, so they can never drift from the saved answers.
"""

from dataclasses import dataclass

from core import db, vectorstore

WEAK_BELOW = 0.60
STRONG_FROM = 0.80
MIN_ANSWERS = 3  # don't judge a topic on fewer answers than this
ADAPTIVE_WEAK_SHARE = 0.60  # share of an adaptive quiz spent on weak topics
# Matching a question to a topic: a fixed similarity cutoff doesn't work (on the Big
# Data notes, correct pairs scored as low as 0.27 while sibling topics like "Sqoop
# import" vs a Sqoop export question scored 0.70), but the closest topic was the right
# one for 9 of 9 questions. So we take the closest of ALL topics, with only a low floor
# to skip questions about none of them (an off-topic question scored 0.16).
TOPIC_MATCH_FLOOR = 0.22

STATUS_LABELS = {
    "weak": "🔴 Weak",
    "learning": "🟡 Learning",
    "strong": "🟢 Strong",
    "new": "⚪ Not tested",
}


@dataclass
class TopicStat:
    topic_id: int
    name: str
    document_id: int | None
    filename: str | None
    answers: int  # all-time answers on this topic
    correct: int  # all-time correct answers
    accuracy: float | None  # over the last db.RECENT_ANSWERS answers; None if untested
    last_seen: str | None
    subject: str | None = None  # the document's subject, if set

    @property
    def status(self) -> str:
        return classify(self.accuracy, self.answers)

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]


def classify(accuracy: float | None, answers: int) -> str:
    if not answers or accuracy is None:
        return "new"
    if answers < MIN_ANSWERS:
        return "learning"
    if accuracy < WEAK_BELOW:
        return "weak"
    if accuracy >= STRONG_FROM:
        return "strong"
    return "learning"


def topic_stats(user_id: int, topic_ids: list[int] | None = None) -> list[TopicStat]:
    """Every topic of the user (or just topic_ids), tested or not."""
    stats = [
        TopicStat(
            topic_id=r["id"],
            name=r["name"],
            document_id=r["document_id"],
            filename=r["filename"],
            answers=r["attempts"] or 0,
            correct=r["correct"] or 0,
            accuracy=r["accuracy"],
            last_seen=r["last_seen"],
            subject=r["subject"],
        )
        for r in db.topic_scores(user_id)
    ]
    if topic_ids is not None:
        wanted = set(topic_ids)
        stats = [s for s in stats if s.topic_id in wanted]
    return stats


def weak_topics(user_id: int) -> list[TopicStat]:
    return sorted(
        (s for s in topic_stats(user_id) if s.status == "weak"), key=lambda s: s.accuracy
    )


def adaptive_allocation(stats: list[TopicStat], n: int) -> dict[int, int]:
    """Spread n questions with ~60% on weak topics (weakest first). The rest go to
    untested topics first (to discover new weak spots), then the lowest-scoring ones,
    then strong topics seen longest ago (a light spaced-repetition touch)."""
    weak = sorted((s for s in stats if s.status == "weak"), key=lambda s: s.accuracy)
    others = sorted(
        (s for s in stats if s.status != "weak"),
        key=lambda s: (
            {"new": 0, "learning": 1, "strong": 2}[s.status],
            s.accuracy if s.accuracy is not None else 0,
            s.last_seen or "",
        ),
    )
    if not weak and not others:
        return {}
    if weak and others:
        weak_n = round(n * ADAPTIVE_WEAK_SHARE)
    else:
        weak_n = n if weak else 0

    allocation: dict[int, int] = {}
    for i in range(weak_n):
        tid = weak[i % len(weak)].topic_id
        allocation[tid] = allocation.get(tid, 0) + 1
    for i in range(n - weak_n):
        tid = others[i % len(others)].topic_id
        allocation[tid] = allocation.get(tid, 0) + 1
    return allocation


def question_topic(user_id: int, text: str) -> TopicStat | None:
    """The topic a question is about: the closest of all the user's topics by
    embedding similarity, or None if nothing is close enough."""
    stats = topic_stats(user_id)
    if not stats or not text.strip():
        return None
    vectors = vectorstore.embed([text] + [s.name for s in stats])
    question = vectors[0]
    similarity, best = max(
        ((sum(a * b for a, b in zip(question, v)), s) for v, s in zip(vectors[1:], stats)),
        key=lambda pair: pair[0],
    )
    return best if similarity >= TOPIC_MATCH_FLOOR else None


def related_weak_topic(user_id: int, text: str) -> TopicStat | None:
    """The question's topic, if it is one of the user's weak topics."""
    topic = question_topic(user_id, text)
    return topic if topic and topic.status == "weak" else None
