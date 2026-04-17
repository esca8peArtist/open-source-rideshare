# ModRun CadQuery Designs

Parametric CAD scripts for the ModRun cable management system.

## Files

| File | Description |
|------|-------------|
| `modrun_clip.py` | Press-fit cable clip — 3mm, 6mm, 12mm bore variants |
| `modrun_rail.py` | Mounting rail — desk-edge clamp and adhesive-base variants |

## Quick Start

```bash
# Install CadQuery
pip install cadquery

# Generate all clip sizes
python modrun_clip.py --output-dir ./stl/

# Generate both rail variants
python modrun_rail.py --output-dir ./stl/

# Custom clip tolerance (if clips are too tight)
python modrun_clip.py --tolerance 0.25 --output-dir ./stl/

# Custom clamp gap (if desk is thicker than 22mm)
python modrun_rail.py --variant desk_clamp --clamp-gap 28 --output-dir ./stl/
```

## Key Parameters to Tune After First Test Print

### Clip (modrun_clip.py)

| Parameter | Default | What it affects |
|-----------|---------|-----------------|
| `SNAP_ARM_THICKNESS` | 1.4mm | Snap stiffness — thinner = easier to insert |
| `SNAP_NUB_HEIGHT` | 1.2mm | Retention force — taller = harder to remove |
| `BORE_GAP_RATIO` | 0.65 | Cable entry ease — higher = easier to press in |
| `FDM_TOLERANCE` | 0.15mm | Slot fit — increase if clip is too tight |

### Rail (modrun_rail.py)

| Parameter | Default | What it affects |
|-----------|---------|-----------------|
| `NUB_RECESS_DEPTH` | 1.4mm | Must be ≥ clip's SNAP_NUB_HEIGHT |
| `CLAMP_ARM_THICKNESS` | 4.0mm | Clamp jaw strength |
| `clamp_gap` (local) | 22.0mm | Jaw opening — default covers ~15–28mm desks |

## Print Settings (Bambu X1C)

**Material**: PLA (standard or matte)
**Layer height**: 0.2mm
**Infill**: 20–25% (gyroid or honeycomb)
**Perimeters**: 3 walls minimum (critical for snap arm durability)
**Supports**: None required if oriented correctly:
  - Clips: print standing on the snap arm base (snap arm faces up)
  - Rails: print flat (long axis along X, lying on the adhesive/clamp face)

**Snap arm orientation**: The snap arm must be printed perpendicular to layer lines
for maximum flex fatigue resistance. The default print orientation achieves this.

## Interface Specification

The clip and rail must use identical slot interface dimensions.
These are defined identically in both scripts:

```
SLOT_WIDTH = 8.0mm     # width of clip slot opening
SLOT_DEPTH = 6.0mm     # depth clip enters the rail
FDM_TOLERANCE = 0.15mm # added clearance on each side
```

If you change these in one file, change them in both.

## Iteration Notes

First test print checklist:
- [ ] Clip snaps into rail slot with moderate force (should not require a tool)
- [ ] Clip does not release under 500g of pull-out force (tugging a cable)
- [ ] Cable presses into bore without excessive force (should not require pliers)
- [ ] Desk clamp grips a 18mm test material without slipping
- [ ] Adhesive base pockets are correct size for Command strips (20×20mm)
- [ ] Rail slots are uniformly spaced at 30mm (measure with calipers)

Expected iteration: 1–3 test prints to tune tolerances for your specific printer.
Document any parameter changes in this README for production repeatability.
