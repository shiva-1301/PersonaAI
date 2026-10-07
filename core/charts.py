"""Altair charts for the Progress page (kept here so they can be rendered and tested
outside Streamlit)."""

import altair as alt
import pandas as pd

from core import memory

SERIES_COLOR = "#2a78d6"  # single series -> one hue (dataviz reference palette, slot 1)
RULE_COLOR = "#8a8984"
ROW_HEIGHT = 26


def topic_accuracy(df: pd.DataFrame) -> alt.LayerChart:
    """Horizontal bars, weakest topic on top, with the weak/strong thresholds.
    df columns: Topic, Accuracy (0-1), Answers, Status, Document."""
    df = df.sort_values("Accuracy")
    bars = (
        alt.Chart(df)
        .mark_bar(color=SERIES_COLOR, cornerRadiusEnd=4, size=14)
        .encode(
            x=alt.X(
                "Accuracy:Q",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%", title=None, values=[0, 0.2, 0.4, 0.6, 0.8, 1]),
            ),
            y=alt.Y("Topic:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
            tooltip=[
                "Topic",
                alt.Tooltip("Accuracy:Q", format=".0%", title="Recent accuracy"),
                "Answers",
                "Status",
                "Document",
            ],
        )
    )
    thresholds = pd.DataFrame(
        {
            "x": [memory.WEAK_BELOW, memory.STRONG_FROM],
            "label": [f"weak < {memory.WEAK_BELOW:.0%}", f"strong ≥ {memory.STRONG_FROM:.0%}"],
        }
    )
    rules = (
        alt.Chart(thresholds)
        .mark_rule(color=RULE_COLOR, strokeWidth=1, strokeDash=[4, 3])
        .encode(x="x:Q", tooltip=[alt.Tooltip("label:N", title="Threshold")])
    )
    labels = (
        alt.Chart(thresholds)
        .mark_text(align="left", baseline="bottom", dx=4, dy=-2, color=RULE_COLOR, fontSize=11)
        .encode(x="x:Q", y=alt.value(0), text="label:N")
    )
    return (bars + rules + labels).properties(height=max(120, ROW_HEIGHT * len(df)))


def score_history(df: pd.DataFrame) -> alt.Chart:
    """Score per quiz, oldest first. df columns: Quiz, Score (0-1), Result, Taken."""
    return (
        alt.Chart(df)
        .mark_line(
            color=SERIES_COLOR, strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True, color=SERIES_COLOR)
        )
        .encode(
            x=alt.X("Quiz:O", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Score:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%", title=None)),
            tooltip=["Quiz", "Result", alt.Tooltip("Score:Q", format=".0%"), "Taken"],
        )
        .properties(height=260)
    )
