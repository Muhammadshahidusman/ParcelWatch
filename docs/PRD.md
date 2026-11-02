# PRD: ParcelWatch Product Requirements

Version 0.1 · 2026-10-25 · Owner: Muhammad Shahid Usman
Source of truth for *what* we build and *why*. Locked parameters live in `CLAUDE.md` and `configs/wake_pilot.yaml`.

## 1. Problem

US counties tax property on its assessed value. When an owner adds a garage, a room or a backyard unit without pulling a building permit, the assessor's office never learns about it, so the improvement stays off the tax roll for years. Field crews can't drive every street, so counties pay vendors to compare aerial photos instead.

The money is real. Vendor case studies report Mohave County, AZ adding over $95 million in market value and $352,000 in yearly tax revenue, and Las Animas County, CO finding $14 million in value from imagery covering one third of the county (EagleView assessor guide).

## 2. Product statement

ParcelWatch compares two dates of free NAIP aerial imagery, detects buildings on both, labels every parcel's change (new, expanded, demolished), checks it against the county permit record, and outputs a ranked list of parcels with unpermitted change plus the estimated missed tax.

## 3. Goals

| # | Goal | Measured by |
| --- | --- | --- |
| G1 | Prove the owner can build an assessor-grade GeoAI change detection pipeline end to end | Working pipeline on the 25 km² Wake County pilot, reproducible from one config file |
| G2 | Show credible accuracy, honestly reported | Precision and miss rate from a 200-parcel checked sample (pilot: Claude's blind chip review, accepted by the owner) |
| G3 | Speak the buyer's language: dollars | Estimated missed assessed value and yearly tax, adjusted by measured precision |
| G4 | Win interviews in the US and Gulf geospatial market | Public repo, public map, case study, LinkedIn post shipped by week 8 |
| G5 | Transferable design | Swapping county = new config file + field mapping, no code rewrite |

### Non-goals (v1)

- Not a commercial SaaS. No logins, billing or multi-tenant backend.
- Not legal evidence. Flags are leads for a field visit, never accusations.
- No whole-county run, no second county, no live imagery feed in v1.
- No oblique imagery, LiDAR or height estimation.
- No detection of pools, decks or patios as separate classes (v1 detects roofed buildings only).

## 4. Target users

| Persona | Who | What they need | How they use ParcelWatch |
| --- | --- | --- | --- |
| **P1: Hiring manager / recruiter** (primary) | GIS or GeoAI lead at an imagery vendor (EagleView, Nearmap, Vexcel), a GIS consultancy, or a Gulf municipality contractor | Proof of skill in under 2 minutes | Opens the web map or README, sees headline numbers, swipes before/after |
| **P2: County assessor / appraisal manager** (realistic buyer) | US assessor office staff, 10 to 100 person office | A short list of parcels worth a field visit, with value at stake | Reviews the ranked parcel table in a private demo |
| **P3: Technical reviewer** | Senior ML or GIS engineer doing a code review | Clean, reproducible, tested code | Clones repo, runs pipeline on sample data, reads TRD |
| **P4: Gulf municipal planner** (secondary market) | Planning or permit compliance staff in Dubai, Riyadh, etc. | Same workflow framed as permit compliance | Reads the case study's "applying this elsewhere" section |

## 5. Key features

Priority: **P0** = must ship in v1, **P1** = ship if on schedule, **P2** = future.

| ID | Feature | Priority | Acceptance criteria |
| --- | --- | --- | --- |
| F1 | Data download | P0 | One command pulls NAIP (2 years), parcels, permits and Overture buildings for the config bbox into `data/raw/` |
| F2 | Image alignment | P0 | After image reprojected onto the exact Before grid in EPSG:26917; offset measured and logged |
| F3 | Building detection v0 (pretrained) | P0 | Building polygons for both years by end of week 2 |
| F4 | Building detection v1 (fine-tuned 4-band Mask R-CNN) | P0 | Beats v0 on the validation sample, or v0 is kept and the reason documented |
| F5 | Object-level change classification | P0 | Every After building labeled new / expanded / unchanged; every unmatched Before building labeled demolished |
| F6 | Parcel roll-up | P0 | One row per changed parcel: counts by change type, added area (m² and sq ft) of the change types that flag (new buildings only) |
| F7 | Permit cross-check | P0 | Each changed parcel gets permit count in the window and `flag_unpermitted`: true when it has a new building and no permit (expansions and demolitions don't flag, since 2026-11-02) |
| F8 | Validation workflow | P0 | Sampling sheet generated; metrics computed after labeling (owner by hand, or an accepted Claude review) |
| F9 | Dollar estimate | P0 | Missed value and yearly tax, raw and precision-adjusted, with the formula shown |
| F10 | Public web map | P0 | Before/after swipe, H3 hex layer, legend, headline stats; works on phone |
| F11 | Case study page + README | P0 | Result-first, includes limitations |
| F12 | Ranked parcel review table (private) | P1 | Sorted by estimated tax, with before/after image chips per parcel |
| F13 | False-alarm cause breakdown | P1 | Counts by cause (trees, shadow, misalignment, trailers, construction) |
| F14 | Second county config | P2 | Runs on a new county with only config changes |
| F15 | REST API | P2 | See TRD section 7 |

## 6. Success metrics

| Metric | Target | How measured |
| --- | --- | --- |
| Precision of unpermitted flags | **≥ 70%** | 100 checked flagged parcels |
| Miss rate in "unchanged" sample | **≤ 10%** (10 of 100) | 100 checked unchanged parcels |
| Pipeline reproducibility | Same outputs on a clean re-run | `parcelwatch` CLI from config only |
| Runtime, local steps | < 30 minutes for the 25 km² box (excluding GPU steps) | Timed run on owner's laptop |
| Web map load | < 3 seconds on 4G, Lighthouse performance ≥ 90 | Lighthouse mobile |
| Shipping | All P0 features by end of week 8 | Checklist below |
| Portfolio outcome | ≥ 5 recruiter or hiring-manager conversations within 6 weeks of launch | Owner tracks |

If precision lands under 70%, we still ship, report the real number, and explain the top 3 false-alarm causes. Honest numbers beat inflated ones.

## 7. Release plan

| Week | Milestone | Features |
| --- | --- | --- |
| 1 | Data in hand | F1 |
| 2 | **Checkpoint: rough end-to-end result** | F2, F3, F5, F6, F7 (rough) |
| 3 to 4 | Fine-tuned model | F4 |
| 5 | Clean change + permit logic | F5 to F7 final, F13 |
| 6 | Validated and priced | F8, F9 |
| 7 to 8 | Shipped | F10, F11, F12 |

## 8. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Permit layer doesn't cover towns in the box | Every change looks unpermitted | **Resolved:** box chosen where 100% of land is county-inspected (79% unincorporated, 13% Wendell, 8% Knightdale), with 2,007 permits in the window |
| Wake's server blocks Pakistan | Can't download parcels or permits | **Resolved:** use ArcGIS Hub full-county downloads |
| Tree canopy and shadows | False alarms and misses | 4-band NIR model, min area filter, document limits |
| NAIP misalignment up to ±6 m | Fake "changes" | Object matching with tolerance, measured offset |
| Parcel splits after Before date | Permits sit on old parent parcel | Spatial permit join, not only PIN join |
| Overture labels imperfect | Weaker model | Spot-check 50 labels before training |
| Scope creep | Never finishing | Week 2 checkpoint, P2 items frozen |

## 9. Positioning (for pitches)

> "I built a working version of the assessor change-detection product on free US data. I work on cadastral and land records every day, so I know why parcels and permits don't line up, and my flags are ones a field team can act on."
