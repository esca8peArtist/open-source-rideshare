"""
ModRun Cable Management Rail — CadQuery parametric design.

Mounting rail with two base variants:
  - Desk-edge clip mount (C-clamp that grips a table edge)
  - Adhesive pad base (flat sole with recessed adhesive-pad pockets)

Clips (see modrun_clips.py) are press-fit into slots along the top
edge of the rail and click in at cable-diameter increments.

All dimensions are in millimetres.

Usage:
    /home/awank/python_env/bin/python3 modrun_rail.py
    # Writes STLs to ../stl/
"""

import os
import cadquery as cq
from cadquery import exporters

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETERS — change these to resize the design
# ─────────────────────────────────────────────────────────────────────────────

# Rail overall size
RAIL_LENGTH         = 200.0   # mm — length (short-side of desk run)
RAIL_WIDTH          = 24.0    # mm — outer width
RAIL_HEIGHT         = 16.0    # mm — total height, base to top

# Cable channel (open at top, runs full length)
CHANNEL_WIDTH       = 16.0    # mm — inner channel width
CHANNEL_DEPTH       = 10.0    # mm — channel depth from top
CHANNEL_WALL        = (RAIL_WIDTH - CHANNEL_WIDTH) / 2  # wall thickness on each side

# Clip slots — rectangular notches in the top rim for press-fit clips
# One slot every SLOT_PITCH mm, starting SLOT_EDGE_OFFSET mm from each end
SLOT_PITCH          = 30.0    # mm — centre-to-centre spacing
SLOT_EDGE_OFFSET    = 20.0    # mm — first slot from rail end
SLOT_WIDTH          = 4.0     # mm — slot opening width (Y direction along rail)
SLOT_DEPTH          = 4.0     # mm — how deep the slot cuts into the rail rim

# Desk-edge clip mount (C-clamp)
CLIP_DESK_THICK     = 25.0    # mm — max desk edge thickness the clip grips
CLIP_ARM_LEN        = 32.0    # mm — how far under-desk the lower arm extends
CLIP_ARM_THICK      = 4.0     # mm — thickness of lower arm
CLIP_ARM_WIDTH      = RAIL_WIDTH   # mm — arm width = rail width
CLIP_BACK_THICK     = 4.0     # mm — vertical back plate thickness
CLIP_SCREW_DIA      = 3.2     # mm — M3 clamping screw clearance hole

# Adhesive base
ADHESIVE_SOLE_H     = 2.5     # mm — extra height of sole plate
ADHESIVE_SOLE_EXTRA = 6.0     # mm — sole wider than rail on each side
ADHESIVE_PAD_DIA    = 20.0    # mm — adhesive pad pocket diameter
ADHESIVE_PAD_DEPTH  = 1.5     # mm — pad pocket depth
ADHESIVE_PAD_OFFS   = 30.0    # mm — pad pocket centre from end

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _slot_positions(length: float) -> list:
    """Return Y positions of clip-slot centres along the rail."""
    available = length - 2 * SLOT_EDGE_OFFSET
    n = max(1, int(available / SLOT_PITCH) + 1)
    step = available / max(1, n - 1) if n > 1 else 0
    return [-length / 2 + SLOT_EDGE_OFFSET + i * step for i in range(n)]


def _base_rail() -> cq.Workplane:
    """
    Rail body with cable channel and clip slots.
    Bottom face sits at Z=0; rail extends from Z=0 to Z=RAIL_HEIGHT.
    Centred at X=0, Y=0.
    """
    L = RAIL_LENGTH
    W = RAIL_WIDTH
    H = RAIL_HEIGHT
    ch_w = CHANNEL_WIDTH
    ch_d = CHANNEL_DEPTH
    slot_w = SLOT_WIDTH
    slot_d = SLOT_DEPTH

    # ── 1. Solid body, bottom at Z=0 ─────────────────────────────────────
    rail = (
        cq.Workplane("XY")
        .box(W, L, H)
        .translate((0, 0, H / 2))
    )

    # ── 2. Cable channel (open at top) ────────────────────────────────────
    # Cut from Z = H down by ch_d. Channel box sits at Z = H - ch_d/2.
    ch_cut = (
        cq.Workplane("XY")
        .box(ch_w, L + 1.0, ch_d)
        .translate((0, 0, H - ch_d / 2))
    )
    rail = rail.cut(ch_cut)

    # ── 3. Clip slots along top rim ───────────────────────────────────────
    # Slots are cut from the TOP of the rail walls (into the wall material,
    # not into the cable channel area). Each slot is on BOTH walls.
    for y_pos in _slot_positions(L):
        # Left wall slot (X = -W/2 side)
        left_slot = (
            cq.Workplane("XY")
            .box(CHANNEL_WALL + 1.0, slot_w, slot_d)
            .translate((-W / 2 + (CHANNEL_WALL + 1.0) / 2 - 0.5, y_pos, H - slot_d / 2))
        )
        # Right wall slot
        right_slot = (
            cq.Workplane("XY")
            .box(CHANNEL_WALL + 1.0, slot_w, slot_d)
            .translate((W / 2 - (CHANNEL_WALL + 1.0) / 2 + 0.5, y_pos, H - slot_d / 2))
        )
        rail = rail.cut(left_slot).cut(right_slot)

    return rail


# ─────────────────────────────────────────────────────────────────────────────
# MOUNTING VARIANTS
# ─────────────────────────────────────────────────────────────────────────────

def build_rail_clip() -> cq.Workplane:
    """
    Rail with desk-edge C-clamp mount.

    The C-clamp wraps around one end of the desk edge:
      ┌──────────────────────────────┐  ← rail top
      │         RAIL BODY            │
      └──────────────────────────────┘  ← rail bottom / desk surface
      │  BACK PLATE  │                  ← down the front face of the desk
      ├──────────────┤                  ← bottom of clamp gap
      │  LOWER ARM   │                  ← under the desk (optional screw hole)

    The back plate and lower arm are at the -Y end of the rail (one end mounts,
    the other end is free). A second clip bracket can be added for longer rails.
    """
    rail = _base_rail()

    L = RAIL_LENGTH
    W = CLIP_ARM_WIDTH
    back_t = CLIP_BACK_THICK
    arm_t = CLIP_ARM_THICK
    arm_l = CLIP_ARM_LEN
    gap = CLIP_DESK_THICK

    # Back plate: runs from rail bottom (Z=0) down to Z=-(gap).
    # Overlaps 2mm into rail end so union is reliable.
    OVERLAP = 2.0
    back_plate = (
        cq.Workplane("XY")
        .box(W, back_t + OVERLAP, gap + arm_t)
        .translate((0, -(L / 2 + back_t / 2 - OVERLAP / 2), -(gap + arm_t) / 2))
    )
    rail = rail.union(back_plate)

    # Lower arm: horizontal, under the desk.
    # Also overlaps back_plate so union is solid.
    lower_arm = (
        cq.Workplane("XY")
        .box(W, arm_l + back_t + OVERLAP, arm_t)
        .translate((0, -(L / 2 + back_t + arm_l / 2 - OVERLAP / 2), -(gap + arm_t / 2)))
    )
    rail = rail.union(lower_arm)

    # Clamping screw hole through lower arm
    screw_cut = (
        cq.Workplane("XZ")
        .workplane(offset=-(L / 2 + back_t + arm_l - 12.0))
        .circle(CLIP_SCREW_DIA / 2)
        .extrude(W + 2, both=True)
        .translate((0, 0, -(gap + arm_t / 2)))
    )
    rail = rail.cut(screw_cut)

    return rail


def build_rail_adhesive() -> cq.Workplane:
    """
    Rail with flat adhesive-pad base.

    A wider sole plate is added beneath the rail with two recessed pockets
    that locate standard 20 mm circular adhesive pads.
    """
    rail = _base_rail()

    L = RAIL_LENGTH
    W = RAIL_WIDTH
    sole_h = ADHESIVE_SOLE_H
    sole_w = W + ADHESIVE_SOLE_EXTRA

    # Sole plate
    sole = (
        cq.Workplane("XY")
        .box(sole_w, L, sole_h)
        .translate((0, 0, -sole_h / 2))
    )
    rail = rail.union(sole)

    # Adhesive pad pockets (recessed into sole bottom face)
    for sign in [-1, 1]:
        y_pad = sign * (L / 2 - ADHESIVE_PAD_OFFS)
        pocket = (
            cq.Workplane("XY")
            .workplane(offset=-sole_h)
            .circle(ADHESIVE_PAD_DIA / 2)
            .extrude(ADHESIVE_PAD_DEPTH + 0.5)
            .translate((0, y_pad, 0))
        )
        rail = rail.cut(pocket)

    return rail


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
    print("Building ModRun rails...")

    print("  [1/2] Desk-edge clip variant...")
    rail_clip = build_rail_clip()
    export_stl(rail_clip, "modrun_rail_clip.stl")

    print("  [2/2] Adhesive base variant...")
    rail_adhesive = build_rail_adhesive()
    export_stl(rail_adhesive, "modrun_rail_adhesive.stl")

    print("Done — 2 rail STLs exported.")
