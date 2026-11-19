"""PDF (reportlab + matplotlib charts), print-friendly HTML and CSV exports."""
from __future__ import annotations

import html
import io
from dataclasses import dataclass, field

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from services.config import DISCLAIMER  # noqa: E402

NAVY, TEAL, AMBER, RED, GREY = "#0B1220", "#14B8A6", "#F59E0B", "#EF4444", "#94A3B8"


@dataclass
class Section:
    heading: str
    text: str = ""
    table: pd.DataFrame | None = None
    chart_png: bytes | None = None
    note: str | None = None          # e.g. "AI draft — review before use"
    tone: str | None = None          # "booked" / "pipeline" to visually separate revenue types
    extra: list = field(default_factory=list)


def df_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


# ------------------------------------------------------------------------------------------------ charts
def line_chart_png(x: list, series: dict[str, list], title: str, ylabel: str = "") -> bytes:
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=150)
    palette = [TEAL, AMBER, "#60A5FA", RED, "#A78BFA"]
    for i, (name, ys) in enumerate(series.items()):
        ax.plot(x, ys, marker="o", lw=2, color=palette[i % len(palette)], label=name)
    _style(ax, title, ylabel)
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=7)
    return _png(fig)


def bar_chart_png(labels: list, values: list, title: str, ylabel: str = "", color: str = TEAL) -> bytes:
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=150)
    ax.bar(labels, values, color=color)
    _style(ax, title, ylabel)
    return _png(fig)


def _style(ax, title, ylabel):
    ax.set_title(title, fontsize=9, loc="left", color="#111827")
    ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(labelsize=7)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ PDF
def build_pdf(title: str, subtitle: str, sections: list[Section]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=title)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=17, textColor=colors.HexColor(NAVY), alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=colors.HexColor(NAVY), spaceBefore=8)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, textColor=colors.HexColor("#6B7280"))
    tag = ParagraphStyle("t", parent=small, textColor=colors.HexColor("#B45309"))
    story = [Paragraph("ONYX | Commercial Intelligence", small), Paragraph(html.escape(title), h1),
             Paragraph(html.escape(subtitle), small), Spacer(1, 6)]
    for s in sections:
        head = s.heading
        if s.tone == "booked":
            head += "  [BOOKED REVENUE]"
        elif s.tone == "pipeline":
            head += "  [POTENTIAL PIPELINE — NOT BOOKED]"
        story.append(Paragraph(html.escape(head), h2))
        if s.note:
            story.append(Paragraph(html.escape(s.note), tag))
        for para in (s.text or "").split("\n"):
            if para.strip():
                story.append(Paragraph(html.escape(para), body))
        if s.chart_png:
            story.append(Image(io.BytesIO(s.chart_png), width=178 * mm, height=64 * mm))
        if s.table is not None and not s.table.empty:
            data = [list(map(str, s.table.columns))] + [[_cell(v) for v in row] for row in s.table.itertuples(index=False)]
            t = Table(data, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story += [Spacer(1, 3), t]
        story.append(Spacer(1, 4))
    story += [Spacer(1, 10), Paragraph(html.escape(DISCLAIMER), small)]
    doc.build(story)
    return buf.getvalue()


def _cell(v) -> str:
    s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    return s if len(s) <= 70 else s[:67] + "…"


# ------------------------------------------------------------------------------------------------ HTML
def build_html(title: str, subtitle: str, sections: list[Section]) -> str:
    import base64
    parts = [f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:Inter,Arial,sans-serif;color:#111827;max-width:820px;margin:24px auto;padding:0 16px;font-size:13px}}
h1{{font-size:22px;margin:4px 0}}h2{{font-size:15px;border-bottom:1px solid #E5E7EB;padding-bottom:4px;margin-top:22px}}
.small{{color:#6B7280;font-size:11px}}.tag{{color:#B45309;font-size:11px}}table{{border-collapse:collapse;width:100%;font-size:11px}}
td,th{{border:1px solid #E5E7EB;padding:4px 6px;text-align:left}}th{{background:#F3F4F6}}
.booked{{border-left:4px solid #14B8A6;padding-left:10px}}.pipeline{{border-left:4px dashed #F59E0B;padding-left:10px}}
img{{max-width:100%}}@media print{{.noprint{{display:none}}}}</style></head><body>
<div class="small">ONYX | Commercial Intelligence</div><h1>{html.escape(title)}</h1><div class="small">{html.escape(subtitle)}</div>
<button class="noprint" onclick="window.print()">Print</button>"""]
    for s in sections:
        cls = f' class="{s.tone}"' if s.tone in ("booked", "pipeline") else ""
        label = {"booked": " — booked revenue", "pipeline": " — potential pipeline (not booked)"}.get(s.tone, "")
        parts.append(f"<section{cls}><h2>{html.escape(s.heading)}{label}</h2>")
        if s.note:
            parts.append(f'<div class="tag">{html.escape(s.note)}</div>')
        for para in (s.text or "").split("\n"):
            if para.strip():
                parts.append(f"<p>{html.escape(para)}</p>")
        if s.chart_png:
            parts.append(f'<img src="data:image/png;base64,{base64.b64encode(s.chart_png).decode()}">')
        if s.table is not None and not s.table.empty:
            parts.append(s.table.to_html(index=False, escape=True, border=0))
        parts.append("</section>")
    parts.append(f'<p class="small">{html.escape(DISCLAIMER)}</p></body></html>')
    return "".join(parts)
