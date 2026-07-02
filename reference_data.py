"""
reference_data.py
-----------------
Fixed business reference data for the cutting optimiser.
Everything here mirrors the rules in the Project Brief (v5):

- Substrate + thickness are FIXED valid combinations, not free-form.
- Four standard stock sheet sizes (plus custom entry in the app).
- Finishing type drives sizing: Edgework and Bevel add +1mm per
  dimension to the ordered size; AsCut uses the exact ordered size.
- Fillers are substrate-specific recurring sizes used to fill waste
  space. This list is editable in the app.
"""

# --- Valid substrate + thickness combinations (mm) ---------------------
SUBSTRATES = {
    "Clear Float": [3, 4, 6, 8],
    "Grey Tint": [4, 6],
    "Bronze Tint": [4, 6],
    "Silvered Mirror": [3, 4, 6],
}

# --- Standard stock sheet sizes (width x height, mm) --------------------
# Width = the long edge = the machine's X axis (horizontal on screen).
STOCK_SIZES = [
    (3300, 2440),
    (3210, 2550),
    (3210, 2440),
    (1070, 2550),
]

# --- Finishing types ----------------------------------------------------
# Allowance = mm added to EACH dimension of the ordered size before cutting.
FINISHING_TYPES = {
    "Edgework": 1,
    "Bevel": 1,
    "AsCut": 0,
}

# --- Default filler sizes per substrate (ordered W x H, mm) -------------
# Fillers are cut at ordered size + edgework allowance like anything else;
# store them here as ORDERED sizes with their finishing type.
DEFAULT_FILLERS = {
    "Silvered Mirror": [
        {"width": 1524, "height": 279, "finishing": "Edgework", "label": "1524 x 279"},
    ],
    "Clear Float": [],
    "Grey Tint": [],
    "Bronze Tint": [],
}

# --- Global rules -------------------------------------------------------
DEFAULT_OVERS_TOLERANCE = 0.10   # 10% acceptable overs unless overridden per job
MIN_TRIM_MM = 8                  # narrowest strip that can physically be broken off
