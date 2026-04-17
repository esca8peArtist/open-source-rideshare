"""
ModRun Cable Management — Parametric Clip

Generates a press-fit cable clip that snaps into the ModRun rail slots.
Three variants: 3mm bore (USB-C), 6mm bore (HDMI/laptop), 12mm bore (thick cables).

Usage:
    python modrun_clip.py --bore 3 --output modrun_clip_3mm.stl
    python modrun_clip.py --bore 6 --output modrun_clip_6mm.stl
    python modrun_clip.py --bore 12 --output modrun_clip_12mm.stl
    python modrun_clip.py --bore 3 --bore 6 --bore 12 --output modrun_clips_all.stl

Requirements:
    pip install cadquery
    or: conda install -c conda-forge cadquery

Geometry overview:
    - Clip body: U-shaped channel that captures the cable
    - Snap arm: a flexible cantilever arm with a locking nub
      that clicks into the rail's slot cross-section
    - The snap arm runs along the back of the clip body
    - Tuning: if the snap is too stiff, reduce SNAP_ARM_THICKNESS
              if the snap doesn't hold, increase SNAP_NUB_HEIGHT
"""

import argparse
import cadquery as cq

# ============================================================
# Global geometry constants — adjust after first test print
# ============================================================

# Rail slot interface dimensions (must match modrun_rail.py)
SLOT_WIDTH = 8.0        # mm — width of rail slot opening
SLOT_DEPTH = 6.0        # mm — depth clip travels into slot
SLOT_INTERFERENCE = 0.3 # mm — total interference fit (split each side = 0.15mm)

# Clip body
BODY_WALL = 2.0         # mm — wall thickness around cable bore
BODY_HEIGHT = 14.0      # mm — height of clip (perpendicular to rail face)
BODY_DEPTH = 10.0       # mm — depth of clip (front to back)

# Cable bore opening — gap at front to allow cable to be pressed in
BORE_GAP_RATIO = 0.65   # 0.65 = gap is 65% of bore diameter; remainder is bridged
                         # Increase if cables are hard to press in; decrease if too loose

# Snap arm dimensions
SNAP_ARM_LENGTH = 8.0       # mm — length of the snap cantilever
SNAP_ARM_THICKNESS = 1.4    # mm — arm thickness; thinner = more flexible
SNAP_ARM_WIDTH = SLOT_WIDTH - 0.4  # mm — leaves 0.2mm clearance each side in slot
SNAP_NUB_HEIGHT = 1.2       # mm — locking nub protrusion; must not exceed slot recess depth
SNAP_NUB_LEAD_ANGLE = 35    # degrees — chamfer angle on the lead face of nub (insertion ease)
SNAP_NUB_LOCK_ANGLE = 80    # degrees — near-vertical face behind nub (retention force)

# Filament: standard FDM tolerances. If printing at 0.2mm layer height, slots
# may need +/- 0.1mm adjustment. Add a tolerance parameter here if needed.
FDM_TOLERANCE = 0.15    # mm — added to slot width clearance on each side


def make_clip_body(bore_diameter: float) -> cq.Workplane:
    """
    Build the main U-channel clip body.
    The channel opens at the front to allow cables to snap in sideways.
    """
    outer_width = bore_diameter + 2 * BODY_WALL
    outer_height = BODY_HEIGHT
    outer_depth = BODY_DEPTH

    # Bore opening gap (front mouth of the U-channel)
    bore_gap = bore_diameter * BORE_GAP_RATIO

    body = (
        cq.Workplane("XY")
        # Outer rectangular block
        .box(outer_width, outer_depth, outer_height)
        # Subtract the cable bore (cylindrical channel through the body)
        .faces(">Z")
        .workplane()
        .center(0, 0)
        .hole(bore_diameter, outer_height)
        # Subtract the front slot opening so cable can be pressed in
        # The slot is bore_gap wide and runs the full height
        .faces(">Y")
        .workplane()
        .center(0, 0)
        .rect(bore_gap, outer_height)
        .cutThruAll()
    )

    # Chamfer the front edges of the opening to guide cable entry
    # This makes pressing the cable in much more forgiving
    entry_chamfer = 0.5
    body = (
        body
        .edges("|Z")
        .edges(">Y")
        .chamfer(entry_chamfer)
    )

    return body


def make_snap_arm(bore_diameter: float) -> cq.Workplane:
    """
    Build the snap arm that clicks into the rail slot.
    The arm is a cantilever attached to the back of the clip body.
    The nub at the free end locks under the rail slot ledge.
    """
    arm_x = SNAP_ARM_WIDTH
    arm_y = SNAP_ARM_LENGTH
    arm_z = SNAP_ARM_THICKNESS

    # Simple arm body: flat rectangular cantilever
    arm = (
        cq.Workplane("XY")
        .box(arm_x, arm_y, arm_z)
    )

    # Add the locking nub at the free end of the arm
    # Nub geometry: lead face chamfered at SNAP_NUB_LEAD_ANGLE, lock face near-vertical
    # We build it as a simple wedge profile extruded across the arm width
    import math
    nub_base = SNAP_NUB_HEIGHT / math.tan(math.radians(SNAP_NUB_LEAD_ANGLE))
    nub_lock = SNAP_NUB_HEIGHT / math.tan(math.radians(SNAP_NUB_LOCK_ANGLE))

    nub_profile = [
        (0, 0),
        (nub_base, SNAP_NUB_HEIGHT),
        (-nub_lock, SNAP_NUB_HEIGHT),
        (-nub_lock, 0),
    ]

    nub = (
        cq.Workplane("XZ")
        .polyline(nub_profile)
        .close()
        .extrude(arm_x)
    )

    # Position nub at the free end of the arm (the end away from the clip body)
    nub = nub.translate((0, arm_y / 2, arm_z / 2))

    arm = arm.union(nub)

    return arm


def make_clip(bore_diameter: float) -> cq.Workplane:
    """
    Assemble the complete clip: body + snap arm.
    The snap arm is positioned on the rear face of the clip body,
    centered, flush with the bottom face (the face that mates with the rail).
    """
    body = make_clip_body(bore_diameter)

    outer_width = bore_diameter + 2 * BODY_WALL
    outer_depth = BODY_DEPTH

    arm = make_snap_arm(bore_diameter)

    # Position arm: centered on the clip's rear face (the -Y face),
    # protruding backward (in -Y direction), centered in X,
    # aligned to the bottom of the clip (the face that sits in the rail slot)
    arm_x_offset = 0
    arm_y_offset = -(outer_depth / 2) - (SNAP_ARM_LENGTH / 2)
    arm_z_offset = -(BODY_HEIGHT / 2) + (SNAP_ARM_THICKNESS / 2)

    arm = arm.translate((arm_x_offset, arm_y_offset, arm_z_offset))

    clip = body.union(arm)

    # Slot interface tabs: two rectangular tabs on either side of the arm base
    # These are what physically enter the rail slot and provide lateral location
    tab_width = (SLOT_WIDTH - FDM_TOLERANCE * 2 - SNAP_ARM_WIDTH) / 2
    tab_height = SLOT_DEPTH
    tab_depth = SLOT_DEPTH  # how far the tab extends into the rail slot

    for sign in [-1, 1]:
        tab_x = sign * (SNAP_ARM_WIDTH / 2 + tab_width / 2)
        tab = (
            cq.Workplane("XY")
            .box(tab_width, tab_depth, tab_height)
            .translate((
                tab_x,
                -(outer_depth / 2) - (tab_depth / 2),
                -(BODY_HEIGHT / 2) + (tab_height / 2)
            ))
        )
        clip = clip.union(tab)

    return clip


def export_clip(bore_diameter: float, output_path: str) -> None:
    """Build and export a clip to STL."""
    print(f"Building clip: bore={bore_diameter}mm → {output_path}")
    clip = make_clip(bore_diameter)
    cq.exporters.export(clip, output_path)
    print(f"  ✓ Exported: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate ModRun cable clip STL files"
    )
    parser.add_argument(
        "--bore",
        type=float,
        action="append",
        default=None,
        metavar="MM",
        help="Cable bore diameter in mm. Repeat for multiple sizes. Default: 3 6 12"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Output directory for STL files (default: current directory)"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=None,
        help=f"Override FDM tolerance (default: {FDM_TOLERANCE}mm). "
             "Increase if clips are too tight; decrease if too loose."
    )
    args = parser.parse_args()

    if args.tolerance is not None:
        global FDM_TOLERANCE
        FDM_TOLERANCE = args.tolerance
        print(f"Using custom FDM tolerance: {FDM_TOLERANCE}mm")

    bore_sizes = args.bore if args.bore is not None else [3.0, 6.0, 12.0]

    import os
    os.makedirs(args.output_dir, exist_ok=True)

    for bore in bore_sizes:
        filename = f"modrun_clip_{int(bore)}mm.stl"
        output_path = os.path.join(args.output_dir, filename)
        export_clip(bore, output_path)

    print(f"\nDone. {len(bore_sizes)} clip(s) exported to {args.output_dir}/")
    print("\nTuning notes:")
    print("  - Snap too stiff to insert: reduce SNAP_ARM_THICKNESS (currently "
          f"{SNAP_ARM_THICKNESS}mm)")
    print("  - Snap releases too easily: increase SNAP_NUB_HEIGHT (currently "
          f"{SNAP_NUB_HEIGHT}mm)")
    print("  - Clip too tight in slot: increase FDM_TOLERANCE (currently "
          f"{FDM_TOLERANCE}mm)")
    print("  - Cable too hard to press in: increase BORE_GAP_RATIO (currently "
          f"{BORE_GAP_RATIO})")


if __name__ == "__main__":
    main()
