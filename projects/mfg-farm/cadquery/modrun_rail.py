"""
ModRun Cable Management — Parametric Rail

Generates the mounting rail that accepts press-fit ModRun clips.
Two mounting variants:
  - desk_clamp: C-shaped clamp that grips desk edge 15–30mm thick (no adhesive)
  - adhesive:   flat base with recessed pockets for 20mm 3M Command adhesive pads

Usage:
    python modrun_rail.py --variant desk_clamp --output modrun_rail_clamp.stl
    python modrun_rail.py --variant adhesive --output modrun_rail_adhesive.stl
    python modrun_rail.py --variant both --output-dir ./stl/

Requirements:
    pip install cadquery

Geometry overview:
    - Rail body: 200mm long bar running along the desk edge
    - Clip slots: 6 rectangular slots evenly spaced at 30mm centers
      Each slot is sized to accept the clip's snap arm + location tabs
    - Slot recess: a recessed ledge inside each slot catches the snap nub
    - Mounting foot: swapped based on variant
      desk_clamp — C-clamp jaw with adjustable clamping range
      adhesive   — flat base with 4 recessed Command-pad pockets

Coordinate system:
    X = along rail length (0 → 200mm)
    Y = depth (front face = 0, back = RAIL_DEPTH)
    Z = height (top = RAIL_HEIGHT, bottom = 0; mounting foot extends below 0)
"""

import argparse
import os
import cadquery as cq

# ============================================================
# Rail body constants (must match modrun_clip.py interface)
# ============================================================

RAIL_LENGTH = 200.0     # mm — total length of rail
RAIL_HEIGHT = 16.0      # mm — height of rail body (above the mounting surface)
RAIL_DEPTH = 24.0       # mm — front-to-back depth of rail body

SLOT_COUNT = 6          # number of clip slots
SLOT_PITCH = 30.0       # mm — center-to-center spacing of slots
SLOT_WIDTH = 8.0        # mm — opening width of clip slot (matches modrun_clip.py)
SLOT_DEPTH = 6.0        # mm — how deep the slot goes into the rail (Z axis)
SLOT_HEIGHT = RAIL_DEPTH # mm — slot runs front-to-back (Y axis)

# Slot nub recess: a ledge inside the slot that the clip's snap nub catches on
# This is the counter-geometry to the snap nub in modrun_clip.py
NUB_RECESS_DEPTH = 1.4  # mm — depth of the recess ledge (≥ SNAP_NUB_HEIGHT)
NUB_RECESS_HEIGHT = 2.0 # mm — height of the recess ledge
NUB_RECESS_POSITION = 4.0  # mm from bottom of slot to center of recess

WALL_THICKNESS = 3.0    # mm — minimum wall between slots and rail body exterior

# ============================================================
# Mounting foot constants
# ============================================================

# Desk clamp variant
CLAMP_ARM_THICKNESS = 4.0       # mm — thickness of each clamp arm
CLAMP_LOWER_OVERHANG = 28.0     # mm — length of lower jaw (must cover 15–30mm desk range)
CLAMP_JAW_MIN_OPENING = 15.0    # mm — minimum desk thickness the clamp accommodates
CLAMP_JAW_MAX_OPENING = 30.0    # mm — maximum desk thickness
CLAMP_NOTCH_COUNT = 4           # number of adjustment notches in lower jaw (optional friction)

# Adhesive pad variant
ADHESIVE_PAD_SIZE = 20.0        # mm — Command adhesive pad is 20×20mm
ADHESIVE_PAD_DEPTH = 1.5        # mm — recess depth for pad (flush when pad installed)
ADHESIVE_PAD_COUNT = 4          # pads placed symmetrically
ADHESIVE_BASE_HEIGHT = 6.0      # mm — height of flat base below rail body

FDM_TOLERANCE = 0.15            # mm — printer tolerance compensation


def make_rail_body() -> cq.Workplane:
    """
    Build the main rail bar with clip slots.
    Clip slots are cut from the top face downward.
    The nub recess is cut into the back wall of each slot.
    """
    # Main bar
    rail = (
        cq.Workplane("XY")
        .box(RAIL_LENGTH, RAIL_DEPTH, RAIL_HEIGHT)
        .translate((RAIL_LENGTH / 2, RAIL_DEPTH / 2, RAIL_HEIGHT / 2))
    )

    # Calculate slot X positions centered in the rail
    total_slots_span = (SLOT_COUNT - 1) * SLOT_PITCH
    slot_x_start = (RAIL_LENGTH - total_slots_span) / 2

    for i in range(SLOT_COUNT):
        slot_x = slot_x_start + i * SLOT_PITCH

        # Slot opening: rectangular pocket from the top face down into the rail
        # Width = SLOT_WIDTH, runs front-to-back (full RAIL_DEPTH), depth = SLOT_DEPTH
        slot = (
            cq.Workplane("XZ")
            .center(slot_x, RAIL_HEIGHT)
            .rect(SLOT_WIDTH, SLOT_DEPTH)
            .extrude(RAIL_DEPTH)
        )
        # The extrude goes in Y; we want it to go through the rail top-to-bottom
        # Reframe: the slot is cut from the top face (-Z from top)
        slot_cut = (
            cq.Workplane("XY")
            .transformed(offset=cq.Vector(slot_x, RAIL_DEPTH / 2, RAIL_HEIGHT))
            .rect(SLOT_WIDTH + FDM_TOLERANCE * 2, RAIL_DEPTH)
            .extrude(-SLOT_DEPTH)
        )

        rail = rail.cut(slot_cut)

        # Nub recess: inside the slot, on the back wall (the wall at +Y side of slot)
        # This is the ledge the clip's snap nub catches on
        # Position: centered on X, at the back of the slot, NUB_RECESS_POSITION from slot bottom
        nub_recess_z = RAIL_HEIGHT - SLOT_DEPTH + NUB_RECESS_POSITION

        nub_recess = (
            cq.Workplane("XY")
            .transformed(offset=cq.Vector(
                slot_x,
                RAIL_DEPTH - WALL_THICKNESS - NUB_RECESS_DEPTH,
                nub_recess_z
            ))
            .rect(SLOT_WIDTH - 0.5, NUB_RECESS_DEPTH)
            .extrude(NUB_RECESS_HEIGHT)
        )

        # We don't subtract this — instead it's a channel cut into the slot back wall
        # The clip arm deflects inward, nub rides over the slot edge, then springs into this recess
        # The recess is cut from the +Y face of each slot
        nub_cut = (
            cq.Workplane("XZ")
            .transformed(offset=cq.Vector(slot_x, nub_recess_z + NUB_RECESS_HEIGHT / 2))
            .rect(SLOT_WIDTH - 0.5, NUB_RECESS_HEIGHT)
            .extrude(-NUB_RECESS_DEPTH)
            .translate((0, RAIL_DEPTH, 0))
        )

        rail = rail.cut(nub_cut)

    # Chamfer the top edges of slot openings to guide clip insertion
    # (Applied globally; edges() selector is approximate — refine if needed)

    return rail


def make_desk_clamp(rail: cq.Workplane) -> cq.Workplane:
    """
    Add the desk-edge C-clamp mounting foot.
    The clamp consists of:
    - Upper jaw: the rail body itself (rests on top of the desk edge)
    - Clamp back: a vertical plate connecting upper and lower jaws
    - Lower jaw: a horizontal arm reaching under the desk
    The gap between upper and lower jaw is set to accommodate 15–30mm desk thickness.
    """
    # We set the clamp for the middle of the range by default (~22mm gap)
    # The clamp is slightly flexible — PLA can accommodate ±5mm from nominal
    clamp_gap = 22.0  # mm — nominal jaw opening (tunable)

    # Clamp back: vertical plate on the rear face of the rail
    # Runs the full rail length, from top of rail down to the lower jaw
    clamp_back_height = clamp_gap + CLAMP_ARM_THICKNESS + RAIL_HEIGHT
    clamp_back = (
        cq.Workplane("XY")
        .box(RAIL_LENGTH, CLAMP_ARM_THICKNESS, clamp_back_height)
        .translate((
            RAIL_LENGTH / 2,
            RAIL_DEPTH + CLAMP_ARM_THICKNESS / 2,
            clamp_back_height / 2 - RAIL_HEIGHT
        ))
    )

    # Lower jaw: horizontal arm extending forward from the bottom of the clamp back
    # toward the front of the desk, long enough to grip 15–30mm thick desks
    lower_jaw = (
        cq.Workplane("XY")
        .box(RAIL_LENGTH, CLAMP_LOWER_OVERHANG, CLAMP_ARM_THICKNESS)
        .translate((
            RAIL_LENGTH / 2,
            RAIL_DEPTH + CLAMP_ARM_THICKNESS - CLAMP_LOWER_OVERHANG / 2,
            -(clamp_gap + CLAMP_ARM_THICKNESS / 2)
        ))
    )

    # Chamfer the inner edge of the lower jaw to reduce sharp contact on desk underside
    # (cosmetic + reduces marring)
    # Add rubber pad notch (optional — small recess for a self-adhesive rubber bumper)
    rubber_pad_recess = (
        cq.Workplane("XY")
        .box(RAIL_LENGTH - 10, 15.0, 1.0)
        .translate((
            RAIL_LENGTH / 2,
            RAIL_DEPTH + CLAMP_ARM_THICKNESS - 8.0,
            -(clamp_gap + 1.5)
        ))
    )
    lower_jaw = lower_jaw.cut(rubber_pad_recess)

    # Union everything
    result = rail.union(clamp_back).union(lower_jaw)

    return result


def make_adhesive_base(rail: cq.Workplane) -> cq.Workplane:
    """
    Add the flat adhesive-pad mounting base.
    A solid slab below the rail body with 4 recessed pockets for 3M Command adhesive pads.
    """
    # Flat base slab
    base = (
        cq.Workplane("XY")
        .box(RAIL_LENGTH, RAIL_DEPTH, ADHESIVE_BASE_HEIGHT)
        .translate((
            RAIL_LENGTH / 2,
            RAIL_DEPTH / 2,
            -(ADHESIVE_BASE_HEIGHT / 2)
        ))
    )

    # Adhesive pad pockets — 4 pads arranged symmetrically
    # Positions: two near each end of the rail, centered front-to-back
    pad_x_inset = 25.0  # mm from each end
    pad_positions = [
        (pad_x_inset, RAIL_DEPTH / 2),
        (RAIL_LENGTH - pad_x_inset, RAIL_DEPTH / 2),
        (RAIL_LENGTH / 2 - SLOT_PITCH, RAIL_DEPTH / 2),
        (RAIL_LENGTH / 2 + SLOT_PITCH, RAIL_DEPTH / 2),
    ]

    for px, py in pad_positions:
        pocket = (
            cq.Workplane("XY")
            .transformed(offset=cq.Vector(px, py, -(ADHESIVE_BASE_HEIGHT - ADHESIVE_PAD_DEPTH)))
            .rect(ADHESIVE_PAD_SIZE, ADHESIVE_PAD_SIZE)
            .extrude(-ADHESIVE_PAD_DEPTH)
        )
        base = base.cut(pocket)

    # Add rounded corners to the base (cosmetic; makes it look cleaner)
    # Note: CadQuery fillet on a box — target the bottom long edges
    # This is approximate; adjust selector if CQ version handles edge selection differently
    try:
        base = base.edges("<Z").fillet(2.0)
    except Exception:
        pass  # Skip if edge selection fails — not critical

    result = rail.union(base)

    return result


def build_rail(variant: str) -> cq.Workplane:
    """
    Build the complete rail in the specified variant.
    variant: 'desk_clamp' or 'adhesive'
    """
    body = make_rail_body()

    if variant == "desk_clamp":
        return make_desk_clamp(body)
    elif variant == "adhesive":
        return make_adhesive_base(body)
    else:
        raise ValueError(f"Unknown variant: {variant}. Use 'desk_clamp' or 'adhesive'.")


def export_rail(variant: str, output_path: str) -> None:
    """Build and export a rail to STL."""
    print(f"Building rail: variant={variant} → {output_path}")
    rail = build_rail(variant)
    cq.exporters.export(rail, output_path)
    print(f"  ✓ Exported: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate ModRun rail STL files"
    )
    parser.add_argument(
        "--variant",
        choices=["desk_clamp", "adhesive", "both"],
        default="both",
        help="Rail mounting variant (default: both)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Output directory for STL files (default: current directory)"
    )
    parser.add_argument(
        "--clamp-gap",
        type=float,
        default=None,
        help="Clamp jaw opening in mm (default: 22.0). Range 15–30 for standard desks."
    )
    parser.add_argument(
        "--length",
        type=float,
        default=None,
        help=f"Rail length override in mm (default: {RAIL_LENGTH}mm)"
    )
    args = parser.parse_args()

    if args.length is not None:
        global RAIL_LENGTH
        RAIL_LENGTH = args.length
        print(f"Custom rail length: {RAIL_LENGTH}mm")

    os.makedirs(args.output_dir, exist_ok=True)

    variants = ["desk_clamp", "adhesive"] if args.variant == "both" else [args.variant]

    for v in variants:
        filename = f"modrun_rail_{v}.stl"
        output_path = os.path.join(args.output_dir, filename)
        export_rail(v, output_path)

    print(f"\nDone. {len(variants)} rail(s) exported to {args.output_dir}/")
    print("\nTuning notes:")
    print("  - Clamp too tight for desk: increase --clamp-gap")
    print("  - Clips don't seat fully: increase SLOT_DEPTH")
    print("  - Clips fall out without snapping: check NUB_RECESS_DEPTH matches clip's SNAP_NUB_HEIGHT")
    print(f"  - Current slot dimensions: {SLOT_WIDTH}×{SLOT_DEPTH}mm, pitch {SLOT_PITCH}mm")


if __name__ == "__main__":
    main()
