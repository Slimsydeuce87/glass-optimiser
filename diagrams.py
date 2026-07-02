"""
diagrams.py -- draws a SheetLayout as a matplotlib figure.
Kept separate from the Streamlit app so it can be tested on its own.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

PALETTE = ["#2E86C1", "#C0392B", "#117A65", "#8E44AD", "#D68910",
           "#2874A6", "#1ABC9C", "#E74C3C", "#5D6D7E", "#A04000"]
FILLER_COLOR = "#909497"


def draw_layout(layout, lines, fillers, split_trim=True):
    """Return a matplotlib Figure for one sheet layout.

    split_trim=True centres the cut area so leftover trim is split
    evenly around the sheet (50/50), matching how it's programmed
    at the machine.
    """
    fig, ax = plt.subplots(figsize=(9, 6.4))
    ax.add_patch(patches.Rectangle((0, 0), layout.sheet_w, layout.sheet_h,
                                   fill=False, edgecolor="black", linewidth=2.5))
    used_h = layout.used_height()
    y = layout.sheet_h
    y_off = (layout.sheet_h - used_h) / 2 if split_trim else 0
    y -= y_off
    labelled = set()
    for band in layout.bands:
        y -= band.height
        x_off = (layout.sheet_w - band.used_width()) / 2 if split_trim else 0
        x = x_off
        for s in band.strips:
            color = (FILLER_COLOR if s.line_index < 0
                     else PALETTE[s.line_index % len(PALETTE)])
            for r in range(s.n_rows):
                ry = y + band.height - (r + 1) * s.cut_height
                ax.add_patch(patches.Rectangle((x, ry), s.cut_width, s.cut_height,
                                               fill=False, edgecolor=color,
                                               linewidth=1.2))
            key = (s.cut_width, s.cut_height, s.line_index)
            if key not in labelled:
                labelled.add(key)
                rot = 90 if s.cut_width < s.cut_height else 0
                ax.text(x + s.cut_width / 2, y + band.height - s.cut_height / 2,
                        f"{s.cut_width}x{s.cut_height}",
                        ha="center", va="center", fontsize=7.5,
                        color=color, rotation=rot)
            x += s.cut_width
    ax.set_xlim(-80, layout.sheet_w + 80)
    ax.set_ylim(-80, layout.sheet_h + 80)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()
    return fig
