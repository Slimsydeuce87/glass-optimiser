"""
app.py -- Glass Cutting Optimiser (v1)
--------------------------------------
Run with:   streamlit run app.py
Then open the address it prints (e.g. http://192.168.x.x:8501) in any
browser on the same network -- desktop or phone.

v1 scope (per Project Brief v5):
- manual entry, one substrate batch at a time
- band-based guillotine optimiser with mixed-width strips and filler fill
- visual cutting diagrams, printable via the browser (Ctrl+P / Share>Print)
"""

import streamlit as st
import pandas as pd

from reference_data import (SUBSTRATES, STOCK_SIZES, FINISHING_TYPES,
                            DEFAULT_FILLERS, DEFAULT_OVERS_TOLERANCE)
from optimiser import JobLine, optimise, summarise

st.set_page_config(page_title="Glass Cutting Optimiser", layout="wide")
st.title("Glass Cutting Optimiser")
st.caption("v1 — manual entry, single-substrate batch, printable cutting diagrams")

# ----------------------------------------------------------------------
# Sidebar: batch settings
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("Batch settings")

    substrate = st.selectbox("Substrate", list(SUBSTRATES.keys()))
    thickness = st.selectbox("Thickness (mm)", SUBSTRATES[substrate])

    stock_labels = [f"{w} x {h}" for w, h in STOCK_SIZES] + ["Custom..."]
    stock_choice = st.selectbox("Stock sheet size", stock_labels)
    if stock_choice == "Custom...":
        c1, c2 = st.columns(2)
        sheet_w = c1.number_input("Width (mm)", 500, 6000, 3300, step=10)
        sheet_h = c2.number_input("Height (mm)", 500, 4000, 2440, step=10)
    else:
        sheet_w, sheet_h = STOCK_SIZES[stock_labels.index(stock_choice)]

    overs_pct = st.number_input("Overs tolerance (%)", 0, 50,
                                int(DEFAULT_OVERS_TOLERANCE * 100),
                                help="Default acceptable overage. "
                                     "Override per line in the table if needed.")

    st.divider()
    st.header("Fillers")
    st.caption("Recurring sizes used to fill waste space (bonus, no target qty).")
    default_fillers = DEFAULT_FILLERS.get(substrate, [])
    filler_df = st.data_editor(
        pd.DataFrame(default_fillers) if default_fillers
        else pd.DataFrame(columns=["width", "height", "finishing", "label"]),
        num_rows="dynamic",
        column_config={
            "width": st.column_config.NumberColumn("Width (mm)", min_value=1),
            "height": st.column_config.NumberColumn("Height (mm)", min_value=1),
            "finishing": st.column_config.SelectboxColumn(
                "Finishing", options=list(FINISHING_TYPES.keys())),
            "label": st.column_config.TextColumn("Label"),
        },
        key="fillers",
    )

# ----------------------------------------------------------------------
# Main: job lines
# ----------------------------------------------------------------------
st.subheader(f"Job lines — {substrate} {thickness}mm")
st.caption("Enter ORDERED sizes; the finishing allowance (+1mm for "
           "Edgework/Bevel) is applied automatically before cutting.")

if "jobs" not in st.session_state:
    st.session_state.jobs = pd.DataFrame(
        columns=["label", "width", "height", "qty", "finishing"])

jobs_df = st.data_editor(
    st.session_state.jobs,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "label": st.column_config.TextColumn("Label / part code"),
        "width": st.column_config.NumberColumn("Width (mm)", min_value=1),
        "height": st.column_config.NumberColumn("Height (mm)", min_value=1),
        "qty": st.column_config.NumberColumn("Qty", min_value=1),
        "finishing": st.column_config.SelectboxColumn(
            "Finishing", options=list(FINISHING_TYPES.keys()),
            help="Must be stated — AsCut means no allowance."),
    },
    key="jobs_editor",
)

run = st.button("Optimise", type="primary", use_container_width=True)

# ----------------------------------------------------------------------
# Diagram drawing lives in diagrams.py (testable without Streamlit)
# ----------------------------------------------------------------------
from diagrams import draw_layout


# ----------------------------------------------------------------------
# Run + results
# ----------------------------------------------------------------------
if run:
    # ---- build JobLine objects from the tables -------------------------
    lines = []
    problems = []
    for i, row in jobs_df.iterrows():
        try:
            if pd.isna(row.get("finishing")) or not row.get("finishing"):
                problems.append(f"Row {i + 1}: finishing type missing — "
                                "must be stated explicitly (or AsCut).")
                continue
            lines.append(JobLine(int(row["width"]), int(row["height"]),
                                 int(row["qty"]), str(row["finishing"]),
                                 str(row.get("label") or f"Line {i + 1}"),
                                 overs_tolerance=overs_pct / 100))
        except (ValueError, TypeError, KeyError):
            problems.append(f"Row {i + 1}: incomplete — needs width, height and qty.")

    fillers = []
    for _, row in filler_df.iterrows():
        try:
            fillers.append(JobLine(int(row["width"]), int(row["height"]), 0,
                                   str(row.get("finishing") or "Edgework"),
                                   str(row.get("label") or "Filler")))
        except (ValueError, TypeError, KeyError):
            pass  # ignore incomplete filler rows

    for p in problems:
        st.warning(p)

    if not lines:
        st.error("Add at least one complete job line, then press Optimise.")
        st.stop()

    with st.spinner("Optimising..."):
        plans, produced, filler_produced = optimise(lines, sheet_w, sheet_h, fillers)

    rows, total_sheets, total_waste = summarise(plans, lines, fillers,
                                                produced, filler_produced)

    # ---- headline + summary table --------------------------------------
    st.success(f"**{total_sheets} sheets — {total_waste}% waste** "
               f"({substrate} {thickness}mm on {sheet_w} x {sheet_h})")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ---- produced vs ordered --------------------------------------------
    prod_rows = []
    for i, ln in enumerate(lines):
        over_pct = (produced[i] - ln.qty) / ln.qty * 100 if ln.qty else 0
        prod_rows.append({
            "Size": ln.display_size(), "Label": ln.label,
            "Produced": produced[i], "Ordered": ln.qty,
            "Overs": f"{over_pct:+.1f}%",
            "Flag": "REVIEW" if produced[i] > ln.max_qty else "",
        })
    for i, f in enumerate(fillers):
        if filler_produced[i]:
            prod_rows.append({"Size": f.display_size(), "Label": f.label,
                              "Produced": filler_produced[i], "Ordered": "-",
                              "Overs": "filler", "Flag": ""})
    st.dataframe(pd.DataFrame(prod_rows), use_container_width=True, hide_index=True)
    if any(r["Flag"] for r in prod_rows):
        st.warning("Flagged lines exceed the overs tolerance — review before cutting.")

    # ---- per-plan diagrams -----------------------------------------------
    split_trim = st.toggle("Show trim split evenly around the sheet "
                           "(50/50, as programmed at the machine)", value=True)
    for p in plans:
        st.subheader(f"Plan {p.plan_number} — {p.sheet_count} sheet"
                     f"{'s' if p.sheet_count != 1 else ''}")
        counts = p.layout.piece_counts()
        parts = []
        for idx, per_sheet in sorted(counts.items()):
            name = (lines[idx].display_size() if idx >= 0
                    else fillers[-idx - 2].display_size() + " (filler)")
            parts.append(f"{per_sheet} x {name}")
        st.caption(" + ".join(parts) + " per sheet  |  "
                   f"waste {p.waste_pct(lines, fillers):.1f}%")
        st.pyplot(draw_layout(p.layout, lines, fillers, split_trim))

    st.info("To print: use your browser's print function (Ctrl+P on desktop, "
            "Share > Print on phone). Each plan diagram prints with its heading.")
