---
title: 3D Print Farm — Business Plan
version: 1.0
date: 2026-04-17
status: active
tags: [3d-printing, business-plan, modrun, etsy, amazon]
---

# 3D Print Farm: Business Plan

**Version 1.0 — April 2026**

This document is the operational plan for the print farm business. The companion document `market-research.md` provides the evidence base for all decisions made here. Read that first.

---

## Executive Summary

**Business**: A one-operator 3D print farm selling original-design functional accessories on Etsy and Amazon, with a clear path from single-printer side income to a multi-printer operation generating $5,000–$10,000/month net.

**Lead product**: ModRun — a modular cable management rail and clip system. Original design. Targets the WFH/gaming desk-setup market.

**Why this wins**:
- Evergreen demand: cable clutter is a permanent problem
- Etsy-compliant: 100% original design (no licensed STL dependency)
- Fast print times: X1C produces 10–20 pieces per overnight run
- Margins: 65–72% net after all fees and packaging at current pricing
- Expandable: same rail accommodates future clip designs; builds a product family

**6-month revenue target**: $1,500–$3,000/month from ModRun alone, with 2 additional product lines launching by Month 4.

**Investment required** (beyond current X1C):
- Filament stock: ~$150 (PLA in 4 colorways, 2kg each)
- Packaging materials: ~$60 (poly mailers, kraft tissue, thank-you cards)
- Optional: $30–60 for professional mockup photos (Canva, or physical lifestyle shots)
- Total launch cost: ~$240

---

## Section 1: Product Catalog

### Phase 1 Products (Launch — Months 1–2)

#### 1A: ModRun Cable Management System

**Status**: Design complete (etsy-listing-modrun.md). Awaiting test print and mockup photos.

| SKU | Description | Material | Weight | Print time | Sale price | Net margin |
|-----|-------------|----------|--------|------------|------------|------------|
| MODRUN-CLIP-5PK-SM | Clip 3mm × 5 | PLA | 25g | 35 min/plate | $8.99 | ~72% |
| MODRUN-CLIP-5PK-MD | Clip 6mm × 5 | PLA | 30g | 40 min/plate | $8.99 | ~71% |
| MODRUN-CLIP-5PK-LG | Clip 12mm × 5 | PLA | 40g | 50 min/plate | $8.99 | ~70% |
| MODRUN-RAIL-CLAMP | Rail, desk-edge clamp | PLA | 60g | 55 min | $12.99 | ~72% |
| MODRUN-RAIL-ADHSV | Rail, adhesive base | PLA | 55g | 50 min | $12.99 | ~73% |
| MODRUN-SET-4PC | 1 rail + 3 clips (SM/MD/LG) | PLA | 135g | ~3h total | $42.99 | ~65% |
| MODRUN-SET-5PC | 1 rail + 3 clips + extra SM 5pk | PLA | 160g | ~3.5h total | $49.99 | ~65% |

**Colors offered**: Matte Black, Matte White, Warm Grey, Natural (cream PLA)
**Material notes**: PETG available on request (bathroom/heat-adjacent installs); $1–2 surcharge

**Margin calculation basis** (4-piece set, $42.99):
- Filament: 135g × $0.015/g = $2.03
- Packaging (poly mailer + tissue): $0.95
- Etsy fees (~20% effective): $8.60
- Shipping: customer pays actual at checkout
- **Net profit: ~$31.41 (73% gross; ~65% after packaging)**

#### 1B: ModRun Color Packs (Expansion SKU, Month 2)

Once the core set has initial reviews:
- MODRUN-CLIP-5PK-SM/MD/LG in Silk Gold, Silk Copper, Glow-in-Dark — $1.50–$2.00 price premium
- These reuse the same design files; zero design investment, ~$0.15 additional material cost per piece

---

### Phase 2 Products (Months 3–4)

**Selection rationale**: After 2 months of ModRun sales, actual revenue and review velocity will indicate whether to deepen the cable management line or launch into a second category. Default plan is below; adjust based on real data.

#### 2A: Original Articulated Animal Line

5 original designs (not IP-adjacent): a geometric axolotl, a fantasy sea creature, an abstract dragon form, a geometric tortoise, and a fractal insect. Each printed in-place, no assembly.

**Target**: Etsy primary. Batch 4–6 per plate overnight.

| SKU | Description | Material | Sale price | Net margin |
|-----|-------------|----------|------------|------------|
| FLEXI-AXOLOTL | Geometric axolotl, single color | PLA/Silk PLA | $14.99 | ~60% |
| FLEXI-AXOLOTL-2C | Geometric axolotl, two-tone AMS | Silk PLA | $18.99 | ~58% |
| FLEXI-SET-3 | 3 random creatures, buyer's choice | PLA | $38.99 | ~62% |

**Design investment**: Commission 5 original STL files from a 3D designer (Fiverr/Upwork). Budget: $150–400 total. This is the primary time/cost gating factor for Phase 2.

#### 2B: Original Planter Line

6 original planter forms: 2 geometric/architectural, 2 organic biomorphic, 1 face concept, 1 hand-holding-pot form. Vase mode printing (fastest, best quality).

| SKU | Description | Material | Sale price | Net margin |
|-----|-------------|----------|------------|------------|
| PLNTR-GEO-SM | Geometric planter, small (100g) | Matte PLA | $16.99 | ~60% |
| PLNTR-GEO-LG | Geometric planter, large (250g) | Matte PLA | $28.99 | ~58% |
| PLNTR-ORG-SM | Organic planter, small | Matte PLA | $18.99 | ~60% |
| PLNTR-FACE-MD | Face planter, medium | Matte PLA | $24.99 | ~60% |

**Design investment**: Originals needed. In-house (Fusion 360 / Blender) or commissioned. Vase-mode planters are among the simpler design challenges — consider learning this as the entry point to in-house design capability.

---

### Phase 3 Products (Months 5–6)

**Trigger-based**: Launch only if Phase 1+2 are generating $2,000+/month combined and printer is capacity-constrained.

Options (pick 1 based on demand signals from Phase 1–2):
- **Pet memorial line** (high margin, low volume, personalization bottleneck)
- **Gaming desk organizer system** (complements ModRun; Amazon-first)
- **Specialty mounts** (appliance-specific, problem-solving category)

---

## Section 2: Product Development Plan

### ModRun (Immediate — Before Launch)

**Step 1: Finalize CadQuery designs** (target: this session)
- Rail (desk-edge clamp variant): parametric CadQuery script → export STL
- Rail (adhesive-pad variant): same base, swap mounting foot
- Clip (3mm, 6mm, 12mm bore): parametric, single script with bore_diameter parameter
- Files in: `projects/mfg-farm/cadquery/`

**Step 2: Test print**
- Print 1 full set in Matte Black (the most common buyer choice)
- Verify: clip snap-fit tension, rail slot dimensions, desk-clamp clamping range (15–30mm)
- Tune geometry if needed: snap arm thickness, slot tolerance, clamp jaw gap
- This is the critical physical gate — do not list until the clip snaps satisfyingly

**Step 3: Photography**
- 5-shot brief already written in `etsy-listing-modrun.md`
- Option A: Print a lifestyle shot setup with real cables on a real desk
- Option B: Use Canva 3D mockup templates (faster but less authentic)
- Minimum: 1 hero shot and 1 detail shot. Do not skip this.

**Step 4: List on Etsy**
- Listing copy is complete in `etsy-listing-modrun.md`
- Hero listing first: 4-piece set ($42.99)
- $1–3/day Etsy Ads budget for first 30 days

**Step 5: Add Amazon Handmade**
- After 25+ Etsy reviews (typically Month 2–3)
- Copy is ready in `etsy-listing-modrun.md`
- Amazon listing benefits from proven demand signal from Etsy

---

### Phase 2 Design Pipeline

**If commissioning (recommended for flexi animals)**:
1. Brief a 3D designer: "5 original articulated flexi creatures, print-in-place, FDM, no IP reference"
2. Platforms: Fiverr (3D printing category), Upwork (CAD/3D design)
3. Budget $30–80 per design; buy all commercial rights
4. Delivery: STL + source file (Blender .blend or Fusion 360 .f3d)
5. Test print each before adding to the catalog

**If in-house (recommended for planters)**:
- Tool: Fusion 360 (free for hobbyists, or pay-to-use) or Blender (free, steeper curve)
- Start with vase-mode planters: they are essentially one-surface solid-of-revolution — the simplest 3D modeling task
- 10–15 hours of practice yields production-ready planter designs
- Skill compounds: every hour of design practice makes future designs faster

---

## Section 3: Fulfillment Workflow

### Order Flow (per unit, end to end)

```
Order received (Etsy or Amazon)
  → Print queue entry (add to next overnight run)
  → Print (unattended overnight batch)
  → Morning QC check:
      - Dimensional check: clip snaps into rail slot? (go/no-go)
      - Surface: no stringing, no layer delamination on visible surfaces
      - Color: consistent with order spec
  → Pack:
      - Small poly mailer (under 1 lb) for clip packs and rails
      - Medium poly mailer (1–2 lb) for full sets
      - Kraft tissue wrap around item
      - Thank-you card (branded, pre-printed batch of 50)
  → Label: Pirateship (discounted USPS rates)
  → Ship: USPS First Class (1–4 business days domestic)
  → Buyer message: "Shipped! Tracking: XXXX" (Etsy auto-sends; Amazon sends automatically)
  → Day 3–4 post-delivery: follow-up message ("Hope it's working well — reviews mean everything")
```

**Target lead time (made to order)**: 2–4 business days. Achievable with overnight print runs.

**Throughput at 1 printer**:
- ModRun 4-piece sets: 2–3 per overnight run (3–4 hours each; batch 2 rails + 6 clip plates simultaneously where plate fits)
- Clip 5-packs alone: 8–12 per overnight run
- At $42.99/set × 2 sets/night × 20 nights/month = $1,720/month floor

---

### Batch Production Workflow

For items without customization (clip packs, rails, flexi animals):

1. **End of workday**: Load printer with correct filament; start overnight batch
2. **Morning**: Unload plate, QC inspect, stage finished inventory
3. **Pack against open orders**: Match FIFO from staged inventory
4. **Ship same-day or next morning**: Pirateship label generation, drop at USPS

**Inventory buffer**: Maintain 5–10 units of each top SKU in finished goods. This enables 1-day shipping on high-volume SKUs and absorbs failed prints without impacting lead time commitments.

---

### Packaging Standards

| Item type | Packaging | Cost |
|-----------|-----------|------|
| Clip 5-packs | 4×8" poly mailer | $0.18–0.25 |
| Single rail | 5×10" poly mailer | $0.22–0.30 |
| 4-piece set | 6×10" poly mailer | $0.30–0.40 |
| Padding | Kraft tissue, $8/250 sheets | $0.03 per unit |
| Brand card | Printed thank-you card, $15/100 | $0.15 per unit |
| **Total packaging** | | **$0.66–$0.80 per unit** |

Source: Uline or UPAKNSHIP for poly mailers (buy 250-pack for lowest per-unit cost).

---

## Section 4: Financial Projections

### Monthly Pro Forma (Conservative Scenario)

Assumptions:
- X1C running 16 productive hours/day, 6 days/week (one day for maintenance/setup)
- ModRun only for months 1–3; Phase 2 products from Month 4
- Etsy fees ~20% (including Offsite Ads if triggered)
- Pirateship USPS rates; shipping charged to buyer at cost
- No FBA; all self-fulfilled
- Material cost: PLA at $15/kg, PETG at $18/kg

| Month | Units sold | Avg sale price | Gross revenue | Platform fees | COGS (mat+pkg) | Net profit |
|-------|-----------|----------------|---------------|---------------|----------------|------------|
| 1 (launch) | 15 | $25 | $375 | $75 | $50 | **$250** |
| 2 | 35 | $28 | $980 | $196 | $100 | **$684** |
| 3 | 60 | $30 | $1,800 | $360 | $175 | **$1,265** |
| 4 (Phase 2 launch) | 80 | $30 | $2,400 | $480 | $220 | **$1,700** |
| 5 | 110 | $32 | $3,520 | $704 | $300 | **$2,516** |
| 6 | 140 | $32 | $4,480 | $896 | $380 | **$3,204** |

**6-month cumulative net profit (conservative)**: ~$9,619

### Monthly Pro Forma (Optimistic Scenario)

Assumes faster review accumulation, one viral listing moment, Phase 2 performs well.

| Month | Units | Revenue | Net profit |
|-------|-------|---------|------------|
| 1 | 25 | $625 | $425 |
| 2 | 60 | $1,680 | $1,150 |
| 3 | 100 | $3,000 | $2,100 |
| 4 | 150 | $4,800 | $3,350 |
| 5 | 200 | $6,400 | $4,500 |
| 6 | 250 | $8,000 | $5,600 |

**6-month cumulative net (optimistic)**: ~$17,125

### Break-Even

X1C ($1,199) + initial filament ($150) + packaging ($60) = $1,409 startup cost.

At conservative Month 3 net profit of $1,265: **break-even by Month 4**.
At optimistic Month 2 net profit of $1,150: **break-even by Month 3**.

---

### Key Cost Items to Track

| Cost | Frequency | Monthly estimate |
|------|-----------|-----------------|
| Filament (PLA, 4 colors) | Per-spool as needed | $60–$150 |
| Packaging materials | Per order | $0.66–0.80/unit |
| Etsy listing fees | Per listing, per renewal | $0.20 × SKUs |
| Etsy Offsite Ads | If triggered | 12–15% on ad-referred sales |
| Amazon Handmade fee | Monthly | $0 (Handmade waives monthly) |
| Pirateship postage | Per shipment | Pass-through |
| Electricity (X1C, 16h/day) | Monthly | ~$8–$12 |
| Printer maintenance | ~$20–40/month amortized | Nozzle: $5; PEI plate: $15/sheet |

---

## Section 5: Machine Investment Timeline

### Current: Bambu X1C

**Capability**: Multi-color (AMS, 4 filaments), 256mm³ build volume, 500mm/s, all engineering materials.
**Use**: Development machine AND production machine during Stage 1.

### Month 4–6: Second Printer Decision Point

**Trigger criteria** (all three must be true):
- Revenue consistently $2,000+/month for 2 consecutive months
- Printer running 80%+ daily (>12 productive hours/day)
- Open order queue consistently >3 business days out

**Recommended addition**: Bambu P1S (~$699 with AMS Lite)
- Same Bambu slicer ecosystem
- Same filament compatibility
- Slightly slower on complex multi-color (AMS Lite = 4 colors, not 16)
- Ideal for volume production of validated SKUs while X1C handles new designs

**ROI**: At $2,000/month and 50% margin, the $700 machine investment is recovered in ~3 weeks of incremental capacity.

### Month 6–9: Resin Printer Consideration

**Trigger**: Only if customer requests for miniature-quality products exceed 15 orders/month.
**Option**: Elegoo Saturn 4 Ultra (~$400) or Bambu B1 (~$600).
**Important**: Resin is a separate operational model — different chemistry, post-processing labor, ventilation requirement. Do not rush this.

### Month 9–12: Laser Cutter Consideration

**Trigger**: Only if total revenue is $4,000+/month AND there is clear demand for personalized wooden/acrylic products.
**Option**: xTool P2 CO2 (~$1,800) — proven for production use, larger work area than entry diode lasers.
**Integration**: Laser-engraved name plaques + 3D-printed memorial frames = hybrid premium product.

---

## Section 6: Marketing and Launch Strategy

### Phase 1 Launch Checklist

- [ ] Test print: full ModRun set; verify clip snap force, rail slot fit, desk clamp range
- [ ] Tune geometry if needed and reprint
- [ ] Photography: 5 shots (brief in etsy-listing-modrun.md)
- [ ] Create Etsy shop (if not already active)
- [ ] Upload 4-piece set listing (hero listing first)
- [ ] Set $1–$3/day Etsy Ads budget
- [ ] Enable "Made to order" flag and set processing time to 2–4 business days
- [ ] Buy packaging materials (poly mailers, tissue, thank-you cards)
- [ ] Create Pirateship account for discounted shipping

### Review Acquisition

Reviews are the single biggest growth lever on Etsy. Without reviews, the listing has no algorithmic standing.

**Target**: 25 reviews on the 4-piece set listing within 90 days.

**Tactics**:
1. Send every buyer a post-delivery message (Day 3–4 after estimated delivery): *"Hi [name], hope the ModRun set is doing its job! If you have a second, even a one-sentence review helps a small shop like ours more than you can imagine."*
2. Keep a 100% response rate on any questions or issues. Etsy weights shop responsiveness in search ranking.
3. Do not request 5-star reviews specifically — Etsy prohibits biased solicitation. Just ask for "a review."
4. Resolve any complaints immediately with a replacement or refund. One 1-star review in the first 25 reviews is disproportionately damaging.

### Etsy SEO

The listing copy in `etsy-listing-modrun.md` is already written with keyword-optimized titles and 13 tags. The key ongoing SEO practices:

- **Refresh stale listings**: Every 3–4 months, edit the title slightly (add/remove one keyword) to signal activity to Etsy's algorithm.
- **Use all 13 tags**: Never leave tags empty. Add seasonal tags when relevant ("home office gift," "desk setup Christmas," etc.).
- **Ship fast**: Etsy prioritizes listings from shops with consistent on-time shipping. 2–3 day processing time, hit it every time.
- **Photograph for mobile**: 70% of Etsy buyers are on mobile. Your thumbnail must be legible at small size. Dark product on light background with no text in the thumbnail performs best.

### Amazon Expansion (Month 3+)

- Launch Amazon Handmade listing after 25+ Etsy reviews
- Amazon copy is in `etsy-listing-modrun.md`
- Amazon's algorithm rewards sales velocity — early sales from Etsy buyers (linked in post-purchase message as "also on Amazon if you know someone who wants one") can seed the Amazon algorithm
- Do not use the same primary keyword in Etsy and Amazon titles if possible — let each platform serve different intent searches

---

## Section 7: Operations and Tooling

### Print Management

**Current**: Bambu Handy app for remote monitoring.
**At 2+ printers**: Add SimplyPrint (integrates with Bambu; multi-printer dashboard, queue management, failure detection via webcam).

**Print queue discipline**:
- Slice all jobs at least 24 hours in advance and add to queue
- Group similar materials/colors per print run to minimize filament swaps
- Run color changes within a single print session if AMS is loaded — avoids manual swap
- Log each print run: start time, filament loaded, job count, output count, fail count

### Order Management

**Current**: Etsy seller app + Amazon Seller Central.
**At $2,000/month**: Consider Craftybase (inventory + COGS tracking for makers). Tracks filament usage per SKU, calculates true COGS per unit, generates profit/loss reports.

### Shipping

**Use Pirateship**:
- Free USPS Commercial Plus rates (typically 15–20% below retail)
- Batch label printing for multiple orders
- No monthly fee (pay per label)
- Integrates with Etsy (auto-imports pending orders, marks them shipped after label purchase)

**Packaging setup**: Designate one small shelf or box as the "pack station." Pre-cut tissue to standard size. Pre-stack poly mailers by size. Having it set up means packing 10 orders takes 20 minutes instead of 45.

---

## Section 8: Key Milestones and Decision Points

| Milestone | Target date | Decision / Action |
|-----------|-------------|-------------------|
| CadQuery designs finalized | April 2026 | → Test print |
| Test print passed | May 2026 | → Photography |
| Photos complete | May 2026 | → Etsy listing goes live |
| First 5 reviews | May–June 2026 | Validate product-market fit; continue |
| First 25 reviews | July 2026 | → Launch Amazon listing |
| $500/month revenue | June–July 2026 | Continue; optimize keywords |
| $1,500/month revenue | July–August 2026 | → Commission Phase 2 designs |
| $2,000/month (2 consecutive) | August–September 2026 | → Evaluate second printer |
| Phase 2 products launched | September 2026 | → Expand to 4–5 active SKU families |
| $4,000/month revenue | October–November 2026 | → Evaluate laser cutter |

---

## Section 9: Risk Register

| Risk | Severity | Probability | Mitigation |
|------|----------|-------------|------------|
| Etsy DMCA false claim on ModRun design | Medium | Low | File STL with US Copyright Office ($65). Keep design files dated and documented. |
| Etsy algorithm deprioritizes listing | Medium | Medium | Multiple listings (clips, rail, set) provide different keyword entry points. 25+ reviews are the primary defense. |
| X1C mechanical failure | High | Low | Bambu spare parts stock: 2 nozzles (0.4mm hardened), 1 PEI plate. 90% of X1C failures are nozzle or plate. |
| Filament price spike (tariffs) | Low | Medium | Maintain 4-week filament buffer in top colors. Qualify 2 US-made suppliers as backup (Hatchbox, Polymaker). |
| Review bomb / competitor attack | Medium | Very Low | Report to Etsy Trust & Safety immediately. Never respond publicly to fake reviews with anything other than a neutral statement. |
| Etsy policy change | High | Low | Cross-list on Amazon from Month 3 onward. Build email list via transactional messages. Never let Etsy be >80% of revenue. |
| Shipping cost increase | Low | Medium | Pirateship hedges against retail rate increases. At $3,000/month, evaluate FBA for top SKU. |
| Competition launches identical design | Medium | Medium | Reviews are the moat. A competitor launching the same design has to climb from 0 reviews against your 100+. Speed matters. |

---

## Appendix: Quick Reference

### SKU Registry

| SKU | Product | Material | Weight | Platform | Price |
|-----|---------|----------|--------|----------|-------|
| MODRUN-CLIP-5PK-SM | Cable clip 3mm × 5 | PLA | 25g | Etsy + Amazon | $8.99 |
| MODRUN-CLIP-5PK-MD | Cable clip 6mm × 5 | PLA | 30g | Etsy + Amazon | $8.99 |
| MODRUN-CLIP-5PK-LG | Cable clip 12mm × 5 | PLA | 40g | Etsy + Amazon | $8.99 |
| MODRUN-RAIL-CLAMP | Rail, desk-edge clamp | PLA | 60g | Etsy + Amazon | $12.99 |
| MODRUN-RAIL-ADHSV | Rail, adhesive base | PLA | 55g | Etsy + Amazon | $12.99 |
| MODRUN-SET-4PC | 4-piece set | PLA | 135g | Etsy + Amazon | $42.99 |
| MODRUN-SET-5PC | 5-piece set | PLA | 160g | Etsy + Amazon | $49.99 |

### Filament Color Stock

| Color | Brand recommendation | Qty to stock | Use |
|-------|---------------------|-------------|-----|
| Matte Black | Bambu PLA Matte or Polymaker Matte | 2kg | Default color |
| Matte White | Same | 1kg | Second most requested |
| Warm Grey | Bambu PLA Matte Stone Grey | 1kg | Option C |
| Natural/Cream | Bambu PLA Basic Beige | 1kg | Option D |
| PETG Black | Bambu PETG | 0.5kg | On-request heat-resistant |

### Weekly Time Budget (Solo Operator, Stage 1)

| Activity | Hours/week |
|----------|-----------|
| Print management (load, monitor, unload) | 2–3 |
| QC inspection and staging | 1–2 |
| Packing and label printing | 3–5 |
| Customer service (messages, reviews) | 1 |
| Design work / listing maintenance | 2–3 |
| Etsy/Amazon analytics review | 0.5 |
| **Total** | **~11–15 hours** |

At 100 units/month output, this is a manageable part-time operation.
