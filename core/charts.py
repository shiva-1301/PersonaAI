"""Plotly charts for the Progress page, in the app's palette (see ui/styles.py)."""

import pandas as pd
import plotly.graph_objects as go

from core import memory

SERIES = "#2A78D6"  # single series -> one hue (palette slot 1)
TEXT = "#1B2559"
MUTED = "#6B7A99"
GRID = "#E6EAF2"
FONT = "Inter, sans-serif"

# Pass as st.plotly_chart(fig, config=PLOTLY_CONFIG): hover stays, the toolbar goes.
PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}


def _layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=16, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=MUTED),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=GRID, font=dict(family=FONT, color=TEXT)),
        showlegend=False,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def score_history(df: pd.DataFrame) -> go.Figure:
    """Score per quiz, oldest first. df columns: Quiz, Score (0-1), Result, Taken."""
    fig = go.Figure(
        go.Scatter(
            x=df["Quiz"], y=df["Score"], mode="lines+markers",
            line=dict(color=SERIES, width=2.5, shape="spline", smoothing=0.6),
            marker=dict(size=9, color=SERIES, line=dict(color="#FFFFFF", width=2)),
            fill="tozeroy", fillcolor="rgba(42, 120, 214, 0.08)",
            customdata=df[["Result", "Taken"]],
            hovertemplate="Quiz %{x}: <b>%{customdata[0]}</b> (%{y:.0%})<br>%{customdata[1]} UTC<extra></extra>",
        )
    )
    fig.update_yaxes(range=[0, 1.05], tickformat=".0%", dtick=0.25)
    fig.update_xaxes(dtick=1, title=dict(text="Quiz", font=dict(size=11)), showgrid=False)
    return _layout(fig, 300)


def topic_accuracy(df: pd.DataFrame) -> go.Figure:
    """Horizontal bars, weakest topic on top, with the weak/strong thresholds.
    df columns: Topic, Accuracy (0-1), Answers, Status, Document."""
    df = df.sort_values("Accuracy")
    fig = go.Figure(
        go.Bar(
            x=df["Accuracy"], y=df["Topic"], orientation="h",
            marker=dict(color=SERIES, cornerradius=4),
            text=[f"{a:.0%}" for a in df["Accuracy"]], textposition="outside", cliponaxis=False,
            textfont=dict(color=MUTED, size=11),
            customdata=df[["Answers", "Status", "Document"]],
            hovertemplate="<b>%{y}</b><br>Recent accuracy %{x:.0%} · %{customdata[0]} answers"
                          "<br>%{customdata[1]} · %{customdata[2]}<extra></extra>",
        )
    )
    for x, label in ((memory.WEAK_BELOW, f"weak < {memory.WEAK_BELOW:.0%}"),
                     (memory.STRONG_FROM, f"strong ≥ {memory.STRONG_FROM:.0%}")):
        fig.add_vline(x=x, line=dict(color=MUTED, width=1, dash="dot"))
        fig.add_annotation(x=x, y=1, yref="paper", yanchor="bottom", xanchor="left", text=label,
                           showarrow=False, font=dict(size=11, color=MUTED))
    fig.update_xaxes(range=[0, 1.1], tickformat=".0%", tickvals=[0, 0.2, 0.4, 0.6, 0.8, 1])
    fig.update_yaxes(autorange="reversed", showgrid=False, ticksuffix="  ")
    fig.update_layout(bargap=0.45)
    fig = _layout(fig, max(160, 30 * len(df) + 60))
    fig.update_layout(margin=dict(l=8, r=16, t=26, b=8))
    return fig
