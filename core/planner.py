"""Study plan generation.

The plan is built by rules, not the LLM, so its guarantees hold every time:
  1. Study time is split across topics by weight: weak 3, untested/learning 2,
     strong 1. Every topic gets at least one 30-minute slot.
  2. Each topic's time is a first study session (~60%) plus a review session with a
     short quiz (~40%), scheduled at least REVIEW_GAP_DAYS later (spaced practice).
  3. The last days before the exam are a mock-quiz day and a weak-topic revision day.
Regenerating re-runs this with the latest topic scores, so improving on a topic
shrinks its share of the plan.
"""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from core import db, memory
from core.memory import TopicStat

WEIGHTS = {"weak": 3, "new": 2, "learning": 2, "strong": 1}
SLOT_HOURS = 0.5  # planning granularity
FIRST_PASS_SHARE = 0.6
REVIEW_GAP_DAYS = 2
MOCK_QUIZ_QUESTIONS = 15


class PlanError(ValueError):
    """The inputs can't produce a plan (exam date passed, too few hours...)."""


@dataclass
class Task:
    kind: str  # "study" | "review" | "mock" | "revision"
    title: str
    hours: float
    topic_id: int | None = None


@dataclass
class Day:
    date: str  # ISO date
    tasks: list[Task] = field(default_factory=list)
    done: bool = False

    @property
    def hours(self) -> float:
        return sum(t.hours for t in self.tasks)


@dataclass
class Plan:
    exam_date: str
    hours_per_day: float
    generated_on: str
    days: list[Day]
    topic_hours: dict[int, float]  # topic_id -> planned hours
    document_ids: list[int] | None = None  # scope to reuse when regenerating; None = all

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        days = [
            Day(d["date"], [Task(**t) for t in d["tasks"]], d.get("done", False))
            for d in data["days"]
        ]
        topic_hours = {int(k): v for k, v in data["topic_hours"].items()}
        return cls(
            data["exam_date"], data["hours_per_day"], data["generated_on"], days, topic_hours,
            data.get("document_ids"),
        )

    def day(self, on: date) -> Day | None:
        return next((d for d in self.days if d.date == on.isoformat()), None)


def build_plan(
    stats: list[TopicStat], exam_date: date, hours_per_day: float, today: date | None = None
) -> Plan:
    today = today or date.today()
    n_days = (exam_date - today).days
    if n_days < 1:
        raise PlanError("The exam date must be after today.")
    if not stats:
        raise PlanError("No topics to plan. Upload notes and check their topics first.")
    slots_per_day = int(hours_per_day / SLOT_HOURS)
    if slots_per_day < 1:
        raise PlanError(f"Plan at least {SLOT_HOURS} hours per day.")

    # Reserve the final day(s): mock quiz, then a last revision of weak topics.
    final_kinds = [] if n_days <= 2 else (["revision"] if n_days <= 6 else ["mock", "revision"])
    study_days = n_days - len(final_kinds)

    # Syllabus order: as the topics appear in each document.
    topics = sorted(stats, key=lambda s: (s.document_id or 0, s.topic_id))
    slots = _allocate_slots(topics, study_days * slots_per_day, study_days, hours_per_day)

    days = [Day((today + timedelta(days=i)).isoformat()) for i in range(n_days)]
    _schedule(days[:study_days], topics, slots, slots_per_day)
    for day, kind in zip(days[study_days:], final_kinds):
        day.tasks = _final_day_tasks(kind, topics, hours_per_day)

    return Plan(
        exam_date=exam_date.isoformat(),
        hours_per_day=hours_per_day,
        generated_on=today.isoformat(),
        days=days,
        topic_hours={t.topic_id: slots[t.topic_id] * SLOT_HOURS for t in topics},
    )


def _allocate_slots(
    topics: list[TopicStat], total: int, study_days: int, hours_per_day: float
) -> dict[int, int]:
    """Split `total` slots by weight (largest remainder), at least one per topic."""
    if total < len(topics):
        needed = math.ceil(len(topics) * SLOT_HOURS / max(study_days, 1) / SLOT_HOURS) * SLOT_HOURS
        raise PlanError(
            f"Not enough time to cover all {len(topics)} topics at {hours_per_day} h/day. "
            f"Plan at least {needed} h/day, or pick fewer documents."
        )
    slots = {t.topic_id: 1 for t in topics}
    remaining = total - len(topics)
    weights = {t.topic_id: WEIGHTS[t.status] for t in topics}
    weight_sum = sum(weights.values())
    shares = {tid: remaining * w / weight_sum for tid, w in weights.items()}
    for tid, share in shares.items():
        slots[tid] += int(share)
    leftover = total - sum(slots.values())
    # Ties go to the heavier (weaker) topic.
    by_remainder = sorted(shares, key=lambda tid: (-(shares[tid] % 1), -weights[tid]))
    for tid in by_remainder[:leftover]:
        slots[tid] += 1
    return slots


def _schedule(
    days: list[Day], topics: list[TopicStat], slots: dict[int, int], per_day: int
) -> None:
    """Fill study days greedily: due reviews first, then the next topics in syllabus
    order. Sessions that don't fit continue on the next day."""
    names = {t.topic_id: t.name for t in topics}
    study = []  # [topic_id, slots_left]
    for t in topics:
        total = slots[t.topic_id]
        # e.g. 1 slot -> study only; 2 -> 1+1; 3 -> 2+1; 5 -> 3+2
        first = max(1, min(total, round(total * FIRST_PASS_SHARE)))
        study.append([t.topic_id, first])
    reviews = []  # [topic_id, slots_left, earliest day index]
    review_slots = {t.topic_id: slots[t.topic_id] - s for t, (_, s) in zip(topics, study)}

    for i, day in enumerate(days):
        free = per_day
        started_today = set()

        def add(kind, tid, n):
            nonlocal free
            title = ("Study: " if kind == "study" else "Review + 5-question quiz: ") + names[tid]
            last = day.tasks[-1] if day.tasks else None
            if last and last.topic_id == tid and last.kind == kind:
                last.hours += n * SLOT_HOURS
            else:
                day.tasks.append(Task(kind, title, n * SLOT_HOURS, tid))
            free -= n

        # 1. Reviews that are due (spaced at least REVIEW_GAP_DAYS after their study).
        for r in reviews:
            if free and r[1] and r[2] <= i:
                n = min(free, r[1])
                add("review", r[0], n)
                r[1] -= n
        # 2. New material in syllabus order.
        while free and study:
            tid, left = study[0]
            n = min(free, left)
            add("study", tid, n)
            started_today.add(tid)
            study[0][1] -= n
            if study[0][1] == 0:
                study.pop(0)
                if review_slots[tid]:
                    reviews.append([tid, review_slots[tid], i + REVIEW_GAP_DAYS])
        # 3. Spare time with nothing due: pull the next reviews forward (but never onto
        #    the day the topic was studied), so no planned time is lost.
        for r in sorted(reviews, key=lambda r: r[2]):
            if free and r[1] and r[0] not in started_today:
                n = min(free, r[1])
                add("review", r[0], n)
                r[1] -= n

    # Anything still unplaced (very short plans) goes on the last study day.
    leftovers = [r for r in reviews if r[1]]
    if leftovers and days:
        for tid, left, _ in leftovers:
            days[-1].tasks.append(
                Task("review", "Review + 5-question quiz: " + names[tid], left * SLOT_HOURS, tid)
            )


def _final_day_tasks(kind: str, topics: list[TopicStat], hours: float) -> list[Task]:
    weak = [t.name for t in sorted(topics, key=lambda t: t.accuracy or 0) if t.status == "weak"]
    if kind == "mock":
        quiz_hours = min(hours, 1.0)
        tasks = [Task("mock", f"Mock exam: {MOCK_QUIZ_QUESTIONS}-question adaptive quiz on all topics", quiz_hours)]
        if hours > quiz_hours:
            tasks.append(Task("mock", "Go through every mock-exam mistake in your notes", hours - quiz_hours))
        return tasks
    focus = ", ".join(weak[:5]) if weak else "the topics you found hardest"
    first = round(hours * 0.6 / SLOT_HOURS) * SLOT_HOURS or hours
    tasks = [Task("revision", f"Final revision of weak topics: {focus}", first)]
    if hours > first:
        tasks.append(Task("revision", "Quick skim of all other topics; rest well before the exam", hours - first))
    return tasks


# --- Persistence ---

def create(
    user_id: int,
    exam_date: date,
    hours_per_day: float,
    document_ids: list[int] | None = None,
    today: date | None = None,
) -> Plan:
    """Build a plan from the user's latest topic scores and save it."""
    stats = memory.topic_stats(user_id)
    if document_ids:
        stats = [s for s in stats if s.document_id in set(document_ids)]
    plan = build_plan(stats, exam_date, hours_per_day, today)
    plan.document_ids = list(document_ids) if document_ids else None
    db.save_study_plan(user_id, plan.exam_date, hours_per_day, json.dumps(plan.to_dict()))
    return plan


def regenerate(user_id: int, old: Plan, today: date | None = None) -> Plan:
    """Same exam, hours and documents; fresh schedule from today with the latest scores."""
    return create(
        user_id, date.fromisoformat(old.exam_date), old.hours_per_day, old.document_ids, today
    )


def latest(user_id: int) -> tuple[int, Plan] | None:
    row = db.latest_study_plan(user_id)
    return (row["id"], Plan.from_dict(json.loads(row["plan_json"]))) if row else None


def save(plan_id: int, plan: Plan) -> None:
    db.update_study_plan(plan_id, json.dumps(plan.to_dict()))


def changes(old: Plan, new: Plan, names: dict[int, str]) -> list[str]:
    """Human-readable differences in hours per topic between two plans."""
    lines = []
    for tid in sorted(set(old.topic_hours) | set(new.topic_hours), key=lambda t: names.get(t, "")):
        before, after = old.topic_hours.get(tid, 0), new.topic_hours.get(tid, 0)
        if before != after:
            lines.append(f"{names.get(tid, 'Topic')}: {before:g} h → {after:g} h")
    return lines
