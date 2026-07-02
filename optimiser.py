"""
optimiser.py
------------
Band-based two-stage guillotine optimiser.

How it mirrors the real planning process:

1. Ordered sizes get the finishing allowance applied (+1mm per dimension
   for Edgework/Bevel) to give CUT sizes.
2. Pieces are grouped by cut HEIGHT. Pieces sharing a height can share
   mixed-width strips in the same band -- this is where the big waste
   savings come from (e.g. 231/331/281-wide pieces all 2074 tall).
3. Sheets are planned one at a time against REMAINING quantities:
     - the tallest band still needed goes across the top of the sheet,
       its width filled with a mix of strip widths from that height group;
     - the leftover band underneath is filled with rows of shorter
       pieces still needed, then filler pieces, tallest-first.
4. Identical sheet layouts are grouped into numbered Plans
   (one structurally-different layout = one plan, never bundled).
5. Waste% counts only uncut trim. Overs within tolerance are USED area.

Deliberately excluded (per brief): process-loss buffering, kerf (none:
score-and-break), machine coordinate output.
"""

from dataclasses import dataclass, field
from typing import Optional
import math

from reference_data import FINISHING_TYPES, MIN_TRIM_MM, DEFAULT_OVERS_TOLERANCE


# ----------------------------------------------------------------------
# Input / output data structures
# ----------------------------------------------------------------------

@dataclass
class JobLine:
    """One ordered line: size is the ORDERED size, before allowance."""
    width: int
    height: int
    qty: int
    finishing: str = "Edgework"
    label: str = ""                       # free text, e.g. customer/part code
    overs_tolerance: Optional[float] = None  # None -> use default (10%)

    @property
    def allowance(self) -> int:
        return FINISHING_TYPES[self.finishing]

    @property
    def cut_width(self) -> int:
        return self.width + self.allowance

    @property
    def cut_height(self) -> int:
        return self.height + self.allowance

    @property
    def cut_size(self) -> tuple:
        return (self.cut_width, self.cut_height)

    @property
    def max_qty(self) -> int:
        """Ordered qty + overs tolerance (rounded down)."""
        tol = DEFAULT_OVERS_TOLERANCE if self.overs_tolerance is None else self.overs_tolerance
        return int(self.qty * (1 + tol))

    def display_size(self) -> str:
        return f"{self.cut_width}x{self.cut_height}"


@dataclass
class PlacedStrip:
    """A vertical strip within a band: one piece size, stacked n_rows high."""
    cut_width: int
    cut_height: int
    n_rows: int
    line_index: int        # which JobLine (or -1 for filler)

    @property
    def pieces(self) -> int:
        return self.n_rows


@dataclass
class Band:
    """A horizontal band across the sheet, containing vertical strips."""
    height: int                       # band height = tallest piece in it
    strips: list = field(default_factory=list)   # list[PlacedStrip]

    def used_width(self) -> int:
        return sum(s.cut_width for s in self.strips)


@dataclass
class SheetLayout:
    """One complete sheet: a stack of bands from the top down."""
    sheet_w: int
    sheet_h: int
    bands: list = field(default_factory=list)

    def used_height(self) -> int:
        return sum(b.height for b in self.bands)

    def piece_counts(self) -> dict:
        """{line_index: count} for this sheet."""
        counts = {}
        for band in self.bands:
            for s in band.strips:
                counts[s.line_index] = counts.get(s.line_index, 0) + s.pieces
        return counts

    def used_area(self, lines, filler) -> int:
        area = 0
        for band in self.bands:
            for s in band.strips:
                area += s.cut_width * s.cut_height * s.pieces
        return area

    def signature(self) -> tuple:
        """Structural fingerprint -- identical signatures = same Plan."""
        sig = []
        for band in self.bands:
            strips = tuple(sorted((s.cut_width, s.cut_height, s.n_rows, s.line_index)
                                  for s in band.strips))
            sig.append((band.height, strips))
        return tuple(sig)


@dataclass
class Plan:
    plan_number: int
    layout: SheetLayout
    sheet_count: int

    def waste_pct(self, lines, filler) -> float:
        sheet_area = self.layout.sheet_w * self.layout.sheet_h
        used = self.layout.used_area(lines, filler)
        return (sheet_area - used) / sheet_area * 100


# ----------------------------------------------------------------------
# Core optimiser
# ----------------------------------------------------------------------

def _width_fill_patterns(widths, sheet_w, max_counts):
    """
    Find combinations of strip widths that fill sheet_w as fully as possible,
    without leaving a sliver of 1..MIN_TRIM_MM-1 at the end, and without
    exceeding max_counts (strips still worth cutting per size).

    widths:      list of (cut_width, key) available in this band
    max_counts:  {key: max strips of this width we could still use}
    Returns the best pattern as {key: n_strips}, or None.
    """
    best = None  # (used_width, pattern_dict)

    def search(i, remaining_w, pattern, used_w):
        nonlocal best
        leftover = remaining_w
        # a pattern is valid if the final leftover is 0 or >= MIN_TRIM_MM
        if leftover == 0 or leftover >= MIN_TRIM_MM:
            if pattern and (best is None or used_w > best[0]):
                best = (used_w, dict(pattern))
        if i >= len(widths):
            return
        w, key = widths[i]
        max_n = min(max_counts.get(key, 0), remaining_w // w) if w > 0 else 0
        # try the highest counts first so good fills are found early
        for n in range(max_n, -1, -1):
            if n:
                pattern[key] = pattern.get(key, 0) + n
            search(i + 1, remaining_w - n * w, pattern, used_w + n * w)
            if n:
                pattern[key] -= n
                if pattern[key] == 0:
                    del pattern[key]

    search(0, sheet_w, {}, 0)
    return best[1] if best else None


def optimise(lines, sheet_w, sheet_h, fillers=None, max_sheets=500):
    """
    Main entry point.

    lines:   list[JobLine]
    fillers: list[JobLine] with qty ignored (unlimited, bonus-only)
    Returns (plans, produced, filler_produced)
      plans:            list[Plan]
      produced:         {line_index: total pieces}
      filler_produced:  {filler_index: total pieces}
    """
    fillers = fillers or []
    remaining = {i: ln.qty for i, ln in enumerate(lines)}
    produced = {i: 0 for i in range(len(lines))}
    filler_produced = {i: 0 for i in range(len(fillers))}

    layouts = []   # every sheet's SheetLayout, in cutting order

    guard = 0
    while any(v > 0 for v in remaining.values()) and guard < max_sheets:
        guard += 1
        layout = _plan_one_sheet(lines, fillers, remaining, produced,
                                 filler_produced, sheet_w, sheet_h)
        if layout is None:
            break   # nothing left fits on a sheet at all
        layouts.append(layout)

    # ---- group identical layouts into numbered Plans -------------------
    plans = []
    by_sig = {}
    for lay in layouts:
        sig = lay.signature()
        if sig in by_sig:
            by_sig[sig].sheet_count += 1
        else:
            plan = Plan(plan_number=len(plans) + 1, layout=lay, sheet_count=1)
            by_sig[sig] = plan
            plans.append(plan)

    return plans, produced, filler_produced


def _plan_one_sheet(lines, fillers, remaining, produced, filler_produced,
                    sheet_w, sheet_h):
    """Plan a single sheet against remaining quantities. Mutates the tallies."""
    layout = SheetLayout(sheet_w=sheet_w, sheet_h=sheet_h)
    height_left = sheet_h
    made_something = False

    while True:
        band = _best_band(lines, fillers, remaining, sheet_w, height_left)
        if band is None:
            break
        # a band must itself not leave an unbreakable sliver below it
        leftover_h = height_left - band.height
        if 0 < leftover_h < MIN_TRIM_MM:
            # shave the band placement: skip this band height (rare edge case)
            break
        layout.bands.append(band)
        height_left -= band.height
        made_something = True
        # update tallies
        for s in band.strips:
            if s.line_index >= 0:
                remaining[s.line_index] = max(0, remaining[s.line_index] - s.pieces)
                produced[s.line_index] += s.pieces
            else:
                filler_idx = -s.line_index - 2   # -2 -> 0, -3 -> 1, ...
                filler_produced[filler_idx] += s.pieces

    return layout if made_something else None


def _best_band(lines, fillers, remaining, sheet_w, height_left):
    """
    Choose the best band for the space left on this sheet.

    Candidate band heights = each distinct cut height still needed that fits.
    For each, pieces are eligible if their cut height EQUALS the band height
    (same-height mixed strips) -- shorter pieces would waste the band's top,
    they get their own shorter band later.  Each strip may stack n_rows if
    n * cut_height fits the band exactly... in a same-height band n_rows = 1.

    Shorter bands below can also stack a piece multiple rows high if its
    height divides the band -- handled by treating (piece, n_rows) as the
    strip unit with strip height = n_rows * cut_height <= band height.
    Filler pieces are only used when no ordered piece fits.
    """
    # distinct candidate heights, tallest first
    heights = sorted({ln.cut_height for i, ln in enumerate(lines)
                      if remaining[i] > 0 and ln.cut_height <= height_left
                      and ln.cut_width <= sheet_w},
                     reverse=True)

    for band_h in heights:
        band = _fill_band(lines, remaining, sheet_w, band_h)
        if band:
            return band

    # nothing ordered fits -> try a filler-only band (bonus material)
    for fi, f in enumerate(fillers):
        if f.cut_height <= height_left and f.cut_width <= sheet_w:
            n = sheet_w // f.cut_width
            leftover = sheet_w - n * f.cut_width
            if n > 0 and (leftover == 0 or leftover >= MIN_TRIM_MM):
                band = Band(height=f.cut_height)
                for _ in range(n):
                    band.strips.append(PlacedStrip(f.cut_width, f.cut_height,
                                                   1, -(fi + 2)))
                return band
    return None


def _fill_band(lines, remaining, sheet_w, band_h):
    """
    Fill a band of height band_h with vertical strips.
    A piece is eligible if n_rows * cut_height <= band_h for some n_rows >= 1
    AND it doesn't waste more than it uses vertically (n_rows*h >= 50% of band,
    so a 300mm piece doesn't sneak into a 2074 band and waste most of it).
    Preference: exact-height pieces first (they define the band).
    """
    # eligible (cut_width, key) options; key = (line_index, n_rows)
    widths = []
    max_counts = {}
    for i, ln in enumerate(lines):
        if remaining[i] <= 0 or ln.cut_width > sheet_w:
            continue
        n_rows = band_h // ln.cut_height
        if n_rows < 1:
            continue
        vertical_use = n_rows * ln.cut_height
        band_leftover = band_h - vertical_use
        if 0 < band_leftover < MIN_TRIM_MM:
            n_rows -= 1                     # avoid an unbreakable sliver
            if n_rows < 1:
                continue
            vertical_use = n_rows * ln.cut_height
        if vertical_use < band_h * 0.5:     # too wasteful for this band
            continue
        key = (i, n_rows)
        widths.append((ln.cut_width, key))
        max_strips = math.ceil(remaining[i] / n_rows)
        max_counts[key] = max_strips

    if not widths:
        return None

    # prefer exact-height pieces by listing them first
    widths.sort(key=lambda wk: (lines[wk[1][0]].cut_height * wk[1][1] != band_h,
                                -wk[0]))

    pattern = _width_fill_patterns(widths, sheet_w, max_counts)
    if not pattern:
        return None

    band = Band(height=band_h)
    for (i, n_rows), n_strips in pattern.items():
        for _ in range(n_strips):
            band.strips.append(PlacedStrip(lines[i].cut_width,
                                           lines[i].cut_height,
                                           n_rows, i))
    return band if band.strips else None


# ----------------------------------------------------------------------
# Reporting helpers
# ----------------------------------------------------------------------

def summarise(plans, lines, fillers, produced, filler_produced):
    """Build a plain-dict summary the app can render as a table."""
    sheet_area = None
    rows = []
    total_sheets = 0
    total_used = 0
    for p in plans:
        sheet_area = p.layout.sheet_w * p.layout.sheet_h
        counts = p.layout.piece_counts()
        parts = []
        for idx, per_sheet in sorted(counts.items()):
            n = per_sheet * p.sheet_count
            if idx >= 0:
                parts.append(f"{n} x {lines[idx].display_size()}")
            else:
                f = fillers[-idx - 2]
                parts.append(f"{n} x {f.display_size()} (filler)")
        used = p.layout.used_area(lines, fillers) * p.sheet_count
        total_used += used
        total_sheets += p.sheet_count
        rows.append({
            "Plan": f"Plan {p.plan_number}",
            "Sheets": p.sheet_count,
            "Pieces produced": " + ".join(parts),
            "Waste %": round(p.waste_pct(lines, fillers), 1),
        })
    total_waste = None
    if sheet_area and total_sheets:
        total_stock = sheet_area * total_sheets
        total_waste = round((total_stock - total_used) / total_stock * 100, 1)
    return rows, total_sheets, total_waste
