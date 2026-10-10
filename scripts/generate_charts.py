"""Chart builders: Plotly figures (dark theme) and inline SVG sparklines."""
import hashlib
import html
import re
from datetime import date

import plotly.graph_objects as go
from markupsafe import Markup
from plotly.offline import get_plotlyjs_version

PLOTLY_JS_URL = f"https://cdn.plot.ly/plotly-basic-{get_plotlyjs_version()}.min.js"
FONT = "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
TEXT = "#C7CEDA"
MUTED = "#7D879A"
GRID = "rgba(255,255,255,0.06)"
CONFIG = {"responsive": True, "displayModeBar": False, "scrollZoom": False}


def _layout(height: int, **extra) -> dict:
    layout = dict(
        height=height,
        autosize=True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=TEXT, size=12),
        margin=dict(l=8, r=8, t=8, b=8),
        hovermode="x unified",
        showlegend=False,
        hoverlabel=dict(bgcolor="#141B2A", bordercolor="rgba(255,255,255,0.12)",
                        font=dict(family=FONT, color="#E8ECF3", size=12)),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
                    font=dict(color=TEXT, size=12), bgcolor="rgba(0,0,0,0)", itemclick="toggle",
                    itemdoubleclick="toggleothers"),
        xaxis=dict(gridcolor=GRID, zeroline=False, showline=False, tickfont=dict(color=MUTED),
                   tickformat="%-d %b", automargin=True, fixedrange=True),
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, tickfont=dict(color=MUTED),
                   automargin=True, fixedrange=True, rangemode="tozero"),
    )
    layout.update(extra)
    return layout


def _html(fig: go.Figure, div_id: str) -> Markup:
    out = fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id, config=CONFIG,
                      default_width="100%")
    # plotly.js loads with `defer`, so run each figure once the DOM (and plotly) is ready.
    out = re.sub(r"<script(?: type=\"text/javascript\")?>(.*?)</script>",
                 lambda m: "<script>document.addEventListener('DOMContentLoaded',function(){" + m.group(1) + "});</script>",
                 out, flags=re.S)
    return Markup(out)


def _rolling(values: list[float], window: int = 7) -> list[float]:
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1):i + 1]
        out.append(round(sum(chunk) / len(chunk), 1))
    return out


def interest_chart(iot: dict, entities: dict, div_id: str, spikes: list | None = None,
                   height: int = 420) -> Markup:
    records = iot.get("data", []) if iot else []
    if not records:
        return Markup('<p class="empty">No search data yet.</p>')
    dates = [r["date"][:10] for r in records]
    fig = go.Figure()
    codes = list(entities)
    for code in codes:
        ent = entities[code]
        daily = [r.get(code, 0) for r in records]
        fig.add_trace(go.Scatter(
            x=dates, y=_rolling(daily), name=ent["short_name"], mode="lines", legendgroup=code,
            line=dict(color=ent["color"], width=2.6, shape="spline", smoothing=0.6),
            hovertemplate=f"{html.escape(ent['short_name'])} %{{y:.1f}}<extra></extra>",
        ))
    for code in codes:
        ent = entities[code]
        fig.add_trace(go.Scatter(
            x=dates, y=[r.get(code, 0) for r in records], name=ent["short_name"], mode="lines",
            legendgroup=code, line=dict(color=ent["color"], width=1.6), visible=False, showlegend=False,
            hovertemplate=f"{html.escape(ent['short_name'])} %{{y}}<extra></extra>",
        ))

    spike_traces = 0
    for s in spikes or []:
        if s["party_code"] not in entities:
            continue
        ent = entities[s["party_code"]]
        label = s.get("explanation") or "No matching headline found"
        label = (label[:90] + "…") if len(label) > 90 else label
        fig.add_trace(go.Scatter(
            x=[s["date"]], y=[s["value"]], mode="markers", showlegend=False, legendgroup=s["party_code"],
            marker=dict(size=11, color="#0B0F17", line=dict(color=ent["color"], width=2.5)),
            hovertemplate=(f"<b>{html.escape(ent['short_name'])} spike</b> {s['ratio']}× normal<br>"
                           f"{html.escape(label)}<extra></extra>"),
        ))
        spike_traces += 1

    n = len(codes)
    vis_smooth = [True] * n + [False] * n + [True] * spike_traces
    vis_daily = [False] * n + [True] * n + [True] * spike_traces
    fig.update_layout(**_layout(
        height,
        showlegend=True,
        updatemenus=[dict(
            type="buttons", direction="right", x=0, xanchor="left", y=1.02, yanchor="bottom",
            bgcolor="rgba(255,255,255,0.04)", bordercolor="rgba(255,255,255,0.10)", borderwidth=1,
            font=dict(color=TEXT, size=11), pad=dict(l=4, r=4, t=2, b=2), showactive=True,
            active=0,
            buttons=[
                dict(label="7-day average", method="update", args=[{"visible": vis_smooth}]),
                dict(label="Daily", method="update", args=[{"visible": vis_daily}]),
            ],
        )],
        margin=dict(l=8, r=8, t=44, b=64),
    ))
    return _html(fig, div_id)


def share_chart(iot: dict, entities: dict, div_id: str, height: int = 300) -> Markup:
    records = iot.get("data", []) if iot else []
    if not records:
        return Markup("")
    dates = [r["date"][:10] for r in records]
    fig = go.Figure()
    for code, ent in entities.items():
        fig.add_trace(go.Scatter(
            x=dates, y=_rolling([r.get(code, 0) for r in records]), name=ent["short_name"],
            mode="lines", stackgroup="one", groupnorm="percent",
            line=dict(color=ent["color"], width=0.5), fillcolor=_alpha(ent["color"], 0.78),
            hovertemplate=f"{html.escape(ent['short_name'])} %{{y:.0f}}%<extra></extra>",
        ))
    fig.update_layout(**_layout(height, showlegend=True, margin=dict(l=8, r=8, t=8, b=60), yaxis=dict(
        gridcolor=GRID, ticksuffix="%", range=[0, 100], tickfont=dict(color=MUTED), fixedrange=True,
        zeroline=False)))
    return _html(fig, div_id)


def poll_trend_chart(polls: list[dict], trend: list[dict], events: list[dict], div_id: str,
                     since: str = "2025-11-01", height: int = 400) -> Markup:
    series = [("LNP", "Coalition", "#3D8BFD"), ("ALP", "Labor", "#F0524A"),
              ("ONP", "One Nation", "#FF8A1F"), ("GRN", "Greens", "#3FCB6E")]
    polls = [p for p in polls if p["date"] >= since]
    trend = [t for t in trend if t["date"] >= since]
    if not polls:
        return Markup('<p class="empty">No polls yet.</p>')
    fig = go.Figure()
    for key, label, color in series:
        pts = [p for p in polls if p.get(f"p_{key}") is not None]
        fig.add_trace(go.Scatter(
            x=[p["date"] for p in pts], y=[p[f"p_{key}"] for p in pts], mode="markers",
            name=label, showlegend=False, marker=dict(size=7, color=_alpha(color, 0.35)),
            text=[html.escape(p["firm"]) for p in pts],
            hovertemplate=f"{label} %{{y}}% · %{{text}}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[t["date"] for t in trend], y=[t[key] for t in trend], mode="lines", name=label,
            line=dict(color=color, width=3, shape="spline", smoothing=0.5),
            hovertemplate=f"{label} average %{{y:.1f}}%<extra></extra>",
        ))
    shapes, annotations = [], []
    shown = [e for e in events if e["date"] >= since]
    for i, e in enumerate(shown):
        shapes.append(dict(type="line", xref="x", yref="paper", x0=e["date"], x1=e["date"], y0=0, y1=1,
                           line=dict(color="rgba(255,255,255,0.18)", width=1, dash="dot")))
        annotations.append(dict(x=e["date"], y=1 - (i % 3) * 0.085, xref="x", yref="paper",
                                text=html.escape(short_event(e["label"])), showarrow=False,
                                hovertext=html.escape(e["label"]),
                                xanchor="left", yanchor="top", font=dict(size=10.5, color=TEXT), xshift=4,
                                bgcolor="rgba(13,19,32,0.85)", borderpad=3))
    top = max([p.get(f"p_{k}") or 0 for p in polls for k, _, _ in series] + [40]) + 18
    fig.update_layout(**_layout(height, shapes=shapes, annotations=annotations, hovermode="closest",
                                showlegend=True, margin=dict(l=8, r=8, t=8, b=60),
                                yaxis=dict(gridcolor=GRID, ticksuffix="%", range=[0, top],
                                           tickfont=dict(color=MUTED), fixedrange=True, zeroline=False)))
    return _html(fig, div_id)


def short_event(label: str) -> str:
    """'Ben Carroll becomes Labor leader and Premier' -> 'Carroll Labor leader'."""
    m = re.match(r"(?:\w+ )?(\w+) becomes (.+?) leader", label)
    if m:
        party = {"Liberal": "Lib", "Labor": "ALP", "One Nation": "ONP", "Greens": "GRN"}.get(m.group(2), m.group(2))
        return f"{m.group(1)} ({party})"
    m = re.search(r"retain (\w+)", label)
    if m:
        return f"{m.group(1)} by-election"
    return label[:22]


def _alpha(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def sparkline_svg(values: list[float], color: str, width: int = 132, height: int = 40) -> Markup:
    if not values or max(values) == min(values) == 0:
        return Markup("")
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / max(len(values) - 1, 1)
    pts = [(i * step, height - 3 - (v - lo) / span * (height - 8)) for i, v in enumerate(values)]
    line = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    area = f"{line} L{width:.1f},{height} L0,{height} Z"
    gid = "g" + hashlib.md5(f"{values}{color}".encode()).hexdigest()[:8]
    last_x, last_y = pts[-1]
    return Markup(
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{color}" stop-opacity="0.35"/>'
        f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
        f'<path d="{area}" fill="url(#{gid})"/>'
        f'<path d="{line}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" '
        f'stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.6" fill="{color}"/></svg>'
    )


def fmt_day(iso: str) -> str:
    return date.fromisoformat(iso[:10]).strftime("%-d %b")
