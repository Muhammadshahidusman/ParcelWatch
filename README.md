# ParcelWatch

Find the buildings the tax roll missed.

ParcelWatch compares two dates of free USDA NAIP aerial imagery, detects buildings on both, labels each parcel's change (new, expanded, demolished), and flags parcels where that change has no matching building permit. Pilot: a 25.0 km² box in east Wake County, NC, 2018 to 2022.

Status: under construction. The result-first README lands in week 8.

```bash
conda env create -f environment.yml   # or: uv venv --python 3.11 .venv
conda activate parcelwatch
pip install -e ".[dev]"
parcelwatch --help
pytest -q
```

Flags are leads from aerial imagery, not findings. A field review is needed before any action.

Imagery: USDA NAIP. Data: Wake County, NC (CC BY 4.0); Overture Maps Foundation (ODbL). Code: MIT.
