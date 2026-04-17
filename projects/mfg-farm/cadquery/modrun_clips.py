"""
ModRun Cable Clips — CadQuery parametric design.

Three variants, one per cable diameter:
  - modrun_clip_3mm.stl   — for ~3 mm cables (phone chargers, thin USB)
  - modrun_clip_6mm.stl   — for ~6 mm cables (standard USB-A, mid-gauge power)
  - modrun_clip_12mm.stl  — for ~12 mm cables (thick monitor cables, power bricks)

Each clip has:
  - A T-slot key on the back that slides into the ModRun rail groove
  - A cable saddle that holds the cable
  - A snap arm that flexes open to receive the cable then clicks shut

All dimensions are in millimetres.

Usage:
    /home/awank/python_env/bin/python3 modrun_clips.py
    # Writes STLs to ../stl/
"""

import os
import cadquery as cq
from cadquery import exporters

# ─────────────────────────────────────────────────────────────────────────────
# SHARED CLIP PARAMETERS — same for all variants
# ─────────────────────────────────────────────────────────────────────────────

# T-slot key dimensions (must match rail T-slot)
KEY_WIDTH           = 7.6     # mm — slightly under TSLOT_WIDTH (8.0) for clearance
KEY_HEIGHT          = 3.8     # mm — slightly under TSLOT_OPENING (4.0) for clearance
KEY_DEPTH           = 3.6     # mm — depth of the key tab (inserted into slot)
KEY_NECK_WIDTH      = 3.6     # mm — neck between key and clip body

# Clip body
BODY_WIDTH          = 18.0    # mm — overall clip width (fits in palm)
BODY_DEPTH          = 10.0    # mm — front-to-back depth of clip body
BODY_HEIGHT         = 12.0    # mm — clip body height (varies slightly per variant)

# Cable saddle
SADDLE_WALL         = 2.0     # mm — wall thickness around cable
SADDLE_FLOOR        = 2.0     # mm — floor thickness under cable

# Snap arm
SNAP_THICKNESS      = 1.8     # mm — snap arm wall thickness
SNAP_LENGTH_FACTOR  = 0.6     # fraction of cable radius used for arm length
SNAP_TIP_WIDTH      = 2.5     # mm — tip of snap arm (retention nub)
SNAP_GAP            = 0.4     # mm — gap between snap tip and saddle (print-clearance)

# Print quality hints (informational)
LAYER_HEIGHT        = 0.2     # mm
INFILL              = 30      # %
MATERIAL            = "PETG"  # recommended for snap arm flex

# ─────────────────────────────────────────────────────────────────────────────
# VARIANT CABLE DIAMETERS
# ─────────────────────────────────────────────────────────────────────────────

VARIANTS = {
    "3mm":  3.0,
    "6mm":  6.0,
    "12mm": 12.0,
}

# ─────────────────────────────────────────────────────────────────────────────
# BUILD FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def build_clip(cable_dia: float) -> cq.Workplane:
    """
    Build a single cable clip for the given cable diameter.

    Parameters
    ----------
    cable_dia : float
        Nominal cable diameter in mm (e.g. 3.0, 6.0, 12.0).
    """
    r = cable_dia / 2.0                      # cable radius
    sw = SADDLE_WALL
    sf = SADDLE_FLOOR
    bw = BODY_WIDTH
    bd = BODY_DEPTH + cable_dia              # total front-to-back scales with cable size
    bh = cable_dia + sf + 4.0               # height: floor + cable + some clearance

    # ── 1. Solid clip body ────────────────────────────────────────────────
    body = (
        cq.Workplane("XY")
        .box(bw, bd, bh)
        .translate((0, 0, bh / 2))
    )

    # ── 2. Cable bore — cylindrical channel through the body ─────────────
    # The cable sits centred in X, near the front face, at height = sf + r
    cable_z = sf + r
    cable_y = bd / 2 - r - sw               # cable near front face

    # Full-length bore (axis = X, through bw)
    bore = (
        cq.Workplane("YZ")
        .workplane(offset=0)
        .center(cable_y, cable_z)
        .circle(r + 0.3)                     # +0.3 clearance
        .extrude(bw + 1, both=True)
    )
    body = body.cut(bore)

    # ── 3. Snap opening — slot from top to bore ───────────────────────────
    # A narrow slot from the top face down to the bore so the cable can click in.
    snap_opening = (
        cq.Workplane("XY")
        .box(bw + 1, SNAP_THICKNESS + SNAP_GAP * 2, bh - cable_z + r + 1)
        .translate((0, cable_y, cable_z + (bh - cable_z + r + 1) / 2))
    )
    body = body.cut(snap_opening)

    # ── 4. T-slot key on back face ────────────────────────────────────────
    # Neck: narrower tab connecting body to the head
    neck = (
        cq.Workplane("XY")
        .box(KEY_NECK_WIDTH, KEY_DEPTH + 1, KEY_HEIGHT)
        .translate((0, -(bd / 2 + KEY_DEPTH / 2 + 0.5), KEY_HEIGHT / 2 + 1.0))
    )
    # Key head (wider T-shape)
    key_head = (
        cq.Workplane("XY")
        .box(KEY_WIDTH, KEY_DEPTH, KEY_HEIGHT)
        .translate((0, -(bd / 2 + KEY_DEPTH), KEY_HEIGHT / 2 + 1.0))
    )
    body = body.union(neck).union(key_head)

    # ── 5. Snap retention nub ─────────────────────────────────────────────
    # Small nub on the inside of the snap gap to hold the cable in
    nub_r = 0.8
    nub = (
        cq.Workplane("XZ")
        .workplane(offset=cable_y - r - 0.3)
        .center(0, cable_z + r + 0.3)
        .circle(nub_r)
        .extrude(bw, both=True)
    )
    body = body.union(nub)

    # ── 6. Chamfer top front edges for easier cable insertion ─────────────
    # (small chamfer — skip if it causes topology errors with older CQ)
    try:
        body = body.edges("|Z").chamfer(0.6)
    except Exception:
        pass  # non-critical; skip if topology issue

    return body


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_stl(model: cq.Workplane, filename: str, tolerance: float = 0.1):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stl")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    exporters.export(model, path, tolerance=tolerance)
    print(f"  Exported → {path}")


if __name__ == "__main__":
    print("Building ModRun cable clips...")
    for label, dia in VARIANTS.items():
        print(f"  [{label}] cable dia={dia}mm...")
        clip = build_clip(cable_dia=dia)
        export_stl(clip, f"modrun_clip_{label}.stl")

    print(f"Done — {len(VARIANTS)} clip STLs exported.")
