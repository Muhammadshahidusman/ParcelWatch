# ParcelWatch

**Find the buildings the tax roll missed.** ParcelWatch compares two dates of free USDA NAIP aerial imagery, detects every building on both, labels each parcel's change (new, expanded, demolished) and flags the parcels where that change has no building permit on file. That's the service US county assessors buy from imagery vendors, because unpermitted construction never reaches the tax roll.

![The same 400 m of east Wake County, NC in 2018 and 2022](web/img/before_after_readme.png)

## Result: east Wake County, NC, 2018 to 2022 (25 km² pilot)

| | |
| --- | --- |
| Parcels in the study box | 5,667 |
| Parcels with detected building change | 2,170 |
| Of those, with no building permit in the window | **1,230** |
| Added area on flagged parcels | 1.62 million sq ft |
| Estimated missed tax, raw | $1.93 million / yr |
| Precision of flags (provisional review, see below) | **20%** (20 of 100 confirmed) |
| Estimated missed tax, adjusted for precision | **$385,300 / yr** |

> **Status (2026-10-26):** the full pipeline runs end to end on real data with the pretrained v0 model. The validation labels are a **provisional** review made from image chips; the owner's own hand check replaces them before any number is quoted. The fine-tuned v1 model is ready to train on Colab. See `HANDOFF.md`.

### What the accuracy check says

The 200-parcel check (100 flagged, 100 unchanged, drawn with `random_state=42` and labeled blind) shows where the baseline model works and where it doesn't:

| What the model claimed | Flags | Confirmed | Precision |
| --- | --- | --- | --- |
| New building | 56 | 19 | 34% |
| Expanded building | 35 | 1 | 3% |
| Demolished only | 8 | 0 | 0% |

New buildings are real a third of the time. "Expanded" flags are almost all outline noise: the pretrained model draws the same roof a little differently each year, and 20 m² is a small margin at 0.6 m pixels. Misses in the unchanged sample ran at 13% (target 10%). The top false-alarm causes are the same house drawn differently or missed in 2018 (44), trees hiding a roof in one year (34), and a trailer and a solar roof (1 each). Precision is far below the 70% target, and it's reported as it stands.

## How it works

1. **Download.** NAIP 2018 (flown 2018-10-22) and 2022 (2022-09-27 and 2022-10-06) from Microsoft Planetary Computer, read as windows of the cloud-optimized tiles. Wake County parcels, building permits and town limits from ArcGIS Hub. Overture building footprints for training labels. Owner, mailing address and site address columns are never read.
2. **Prepare.** Both years go onto one 0.6 m grid in NAD83 / UTM 17N. The offset between years is measured at 5 road intersections that exist in both years (provisional automatic estimate: 4.4 m max), giving a 5.4 m match tolerance. The 2018 image is histogram-matched to 2022 as detector input, because the pretrained model found half as many 2018 houses on the hazier original.
3. **Detect.** The same model with the same settings on both years: GeoAI's pretrained building extractor (v0), then a 4-band Mask R-CNN fine-tuned on Overture labels (v1). v1 replaces v0 only if it's at least as precise on the same 200 parcels.
4. **Compare buildings, not pixels.** NAIP is accurate to about ±6 m, so pixel differencing would light up every roof edge. A 2022 building with no 2018 match is new; +20 m² and 1.2× the old area is expanded; a 2018 building with no 2022 match is demolished.
5. **Check permits.** A changed parcel is permitted if a building-related permit issued between 2017-10-22 and 2022-10-06 sits inside it or carries its parcel number (1,898 such permits in the box).
6. **Price and publish.** Value per sq ft is the median `BLDG_VAL / HEATEDAREA` of 1,103 homes built since 2021 in the box ($172.25). Tax uses 2026 rates (county 53.71¢ per $100, plus Wendell 42.00¢ or Knightdale 44.00¢), fire tax excluded, then multiplied by measured precision. The public map shows H3 hexagons with at least 5 parcels; no parcel, address or owner is ever published.

## Run it yourself

```bash
uv venv --python 3.11 .venv          # or: conda env create -f environment.yml
source .venv/Scripts/activate        # Windows Git Bash; .venv/bin/activate elsewhere
uv pip install -e ".[dev,ml]"

parcelwatch download --config configs/wake_pilot.yaml   # ~600 MB
parcelwatch prepare  --config configs/wake_pilot.yaml
parcelwatch detect   --config configs/wake_pilot.yaml --model v0   # ~35 min on CPU
parcelwatch changes  --config configs/wake_pilot.yaml --model v0
parcelwatch validate --config configs/wake_pilot.yaml --make-sheet  # then label, then --score
parcelwatch report   --config configs/wake_pilot.yaml
pytest -q                                                # 85 tests, no network or GPU
```

Every number, URL, date and field name lives in `configs/wake_pilot.yaml`. Another county is a new config file. Design and decisions: `CLAUDE.md`, `docs/PRD.md`, `docs/TRD.md`, `docs/DESIGN.md`.

## Limitations

- Flags are leads from aerial imagery, not findings. A field review is needed before any action.
- The v0 baseline's expanded-building flags are mostly noise; trees and shadows cause both false alarms and misses.
- Additions under 20 m² can't be told apart from noise at NAIP's resolution and accuracy.
- Only roofed buildings count: no pools, decks, patios or interior work.
- A permit anywhere in the window covers the whole parcel.
- One value per sq ft for the whole area; real assessments vary by house.

## Credits and license

Imagery: USDA NAIP. Data: Wake County, NC (CC BY 4.0); Overture Maps Foundation (ODbL). Code: MIT, © 2026 Muhammad Shahid Usman (mapsync360@gmail.com).
