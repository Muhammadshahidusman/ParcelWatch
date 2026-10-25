"""Private review tools: image chips, the blind labeling helper (F8) and the ranked
parcel review table (F12). Everything here stays in ``results/`` and is never deployed."""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from parcelwatch.config import Config
from parcelwatch.paths import Paths

log = logging.getLogger(__name__)

CHIP_PX = 256
CHIP_PAD_M = 12.0
FLAG_RGB = (204, 121, 167)  # --chg-flag #CC79A7


def _square_bounds(geom: object, pad: float) -> tuple[float, float, float, float]:
    """Square bounds around a geometry plus padding."""
    x0, y0, x1, y1 = geom.bounds  # type: ignore[attr-defined]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = max(x1 - x0, y1 - y0) / 2 + pad
    half = min(max(half, 25.0), 120.0)
    return (cx - half, cy - half, cx + half, cy + half)


def render_chip(raster: Path, geom: object, out: Path, px: int = CHIP_PX) -> Path:
    """Save an RGB PNG chip of ``raster`` around ``geom`` with the parcel outlined.

    Args:
        raster: Before or aligned After mosaic.
        geom: Parcel polygon in the raster CRS.
        out: PNG path.
        px: Chip size in pixels.

    Returns:
        ``out``.
    """
    import rasterio
    from PIL import Image, ImageDraw
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    b = _square_bounds(geom, CHIP_PAD_M)
    with rasterio.open(raster) as src:
        win = from_bounds(*b, transform=src.transform)
        arr = src.read(
            [1, 2, 3],
            window=win,
            out_shape=(3, px, px),
            boundless=True,
            resampling=Resampling.bilinear,
        )
    img = Image.fromarray(np.moveaxis(arr, 0, -1).astype("uint8"))
    draw = ImageDraw.Draw(img)
    sx = px / (b[2] - b[0])
    for poly in getattr(geom, "geoms", [geom]):
        ring = [((x - b[0]) * sx, (b[3] - y) * sx) for x, y in poly.exterior.coords]
        draw.line(ring, fill=FLAG_RGB, width=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def render_pair(before: Path, after: Path, geom: object, out: Path, title: str = "") -> Path:
    """Save Before and After chips side by side in one PNG (for quick review)."""
    from PIL import Image, ImageDraw

    tmp_b, tmp_a = out.with_suffix(".b.png"), out.with_suffix(".a.png")
    render_chip(before, geom, tmp_b)
    render_chip(after, geom, tmp_a)
    canvas = Image.new("RGB", (CHIP_PX * 2 + 8, CHIP_PX + 22), "white")
    canvas.paste(Image.open(tmp_b), (0, 22))
    canvas.paste(Image.open(tmp_a), (CHIP_PX + 8, 22))
    d = ImageDraw.Draw(canvas)
    d.text((4, 4), f"BEFORE  {title}", fill="black")
    d.text((CHIP_PX + 12, 4), "AFTER", fill="black")
    canvas.save(out)
    tmp_b.unlink()
    tmp_a.unlink()
    return out


def write_chips(cfg: Config, rows: gpd.GeoDataFrame, key: str, out_dir: Path) -> None:
    """Render Before, After and pair chips for each row, named by ``rows[key]``."""
    p = Paths(cfg.root)
    for k, geom in zip(rows[key], rows.geometry, strict=True):
        b, a = out_dir / f"{k}_before.png", out_dir / f"{k}_after.png"
        if not b.exists():
            render_chip(p.naip_before, geom, b)
        if not a.exists():
            render_chip(p.naip_after_aligned, geom, a)
        pair = out_dir / f"{k}_pair.png"
        if not pair.exists():
            render_pair(p.naip_before, p.naip_after_aligned, geom, pair, str(k))


_CSS = """
:root{--bg:#FFFFFF;--surface:#F6F7F9;--border:#E3E6EA;--ink:#0F172A;--ink-muted:#5B6676;
--accent:#0F766E;--accent-ink:#FFFFFF;--flag:#CC79A7}
@media (prefers-color-scheme:dark){:root{--bg:#0B0F14;--surface:#141A21;--border:#2A333D;
--ink:#E6EAF0;--ink-muted:#9AA5B4;--accent:#2DD4BF;--accent-ink:#0B0F14}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/26px Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--border);
padding:12px 24px;display:flex;gap:16px;align-items:center;z-index:2}
h1{font-size:18px;margin:0;font-weight:600}.muted{color:var(--ink-muted);font-size:13px}
main{padding:16px 24px;display:grid;gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;
display:grid;grid-template-columns:auto auto 1fr;gap:12px;align-items:start}
.card img{width:256px;height:256px;border-radius:6px;display:block}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:14px}
fieldset{border:0;padding:0;margin:0}label{display:block;cursor:pointer;min-height:28px}
button{background:var(--accent);color:var(--accent-ink);border:0;border-radius:6px;
height:40px;padding:0 16px;font:inherit;cursor:pointer}
select,input[type=text]{font:inherit;padding:4px 8px;border-radius:6px;border:1px solid var(--border);
background:var(--bg);color:var(--ink);width:100%}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.done{border-color:var(--accent)}
@media (max-width:900px){.card{grid-template-columns:1fr}.card img{width:100%;height:auto}}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--border);
padding:8px;text-align:left;vertical-align:middle}th{font-size:13px;color:var(--ink-muted)}
td img{width:80px;height:80px;border-radius:4px}.num{text-align:right}
"""


def write_labeling_helper(cfg: Config, sheet: pd.DataFrame) -> Path:
    """Write ``results/validation_helper.html``: blind Before/After cards with label inputs.

    The helper never shows the group (flagged or unchanged) or any detection, so labels
    are unbiased. Labels autosave in the browser and export to ``validation_labels.csv``.

    Args:
        cfg: Loaded config (labels and false-alarm causes).
        sheet: Validation sheet.

    Returns:
        Path of the HTML file.
    """
    p = Paths(cfg.root)
    chips = p.results / "chips" / "validation"
    g = gpd.GeoDataFrame(
        sheet[["sample_id", "parcel_id"]],
        geometry=gpd.read_file(p.parcels_clipped)
        .set_index(cfg.fields.parcel_id)
        .geometry.reindex(sheet["parcel_id"].astype(str))
        .to_numpy(),
        crs=cfg.aoi.working_crs,
    )
    missing = g.geometry.isna()
    if missing.any():
        log.warning("%d sample parcels have no geometry", int(missing.sum()))
    write_chips(cfg, g[~missing], "sample_id", chips)
    labels = cfg.validation.labels
    causes = cfg.validation.false_alarm_causes
    cards = []
    for sid in sheet["sample_id"]:
        radios = "".join(
            f'<label><input type="radio" name="{sid}" value="{lab}"> {lab.replace("_", " ")}</label>'
            for lab in labels
        )
        opts = "".join(f'<option value="{c}">{c.replace("_", " ")}</option>' for c in causes)
        cards.append(
            f'<section class="card" id="{sid}"><img src="chips/validation/{sid}_before.png" '
            f'alt="{sid} 2018"><img src="chips/validation/{sid}_after.png" alt="{sid} 2022">'
            f'<div><div class="mono">{sid}</div><p class="muted">Inside the pink outline, what '
            f"changed between {cfg.imagery.before.year} (left) and {cfg.imagery.after.year} "
            f"(right)?</p><fieldset>{radios}</fieldset><p class='muted'>If no change: what might "
            f'fool a detector here?</p><select data-cause="{sid}"><option value=""></option>{opts}'
            f'</select><p></p><input type="text" data-note="{sid}" placeholder="Note"></div></section>'
        )
    ids = json.dumps(list(sheet["sample_id"]))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Validation Labeling</title><style>{_CSS}</style></head><body>
<header><h1>ParcelWatch validation</h1><span class="muted" id="count"></span>
<span style="flex:1"></span><button id="export">Export validation_labels.csv</button></header>
<main>{"".join(cards)}</main>
<script>
const IDS={ids};const KEY="parcelwatch-labels";
let store={{}};try{{store=JSON.parse(localStorage.getItem(KEY)||"{{}}")}}catch(e){{}}
function save(){{try{{localStorage.setItem(KEY,JSON.stringify(store))}}catch(e){{}}refresh()}}
function refresh(){{let n=0;for(const id of IDS){{const s=store[id]||{{}};
document.getElementById(id).classList.toggle("done",!!s.label);if(s.label)n++}}
document.getElementById("count").textContent=n+" of "+IDS.length+" labeled"}}
for(const id of IDS){{const s=store[id]||{{}};
document.querySelectorAll(`input[name="${{id}}"]`).forEach(r=>{{r.checked=r.value===s.label;
r.onchange=()=>{{store[id]={{...store[id],label:r.value}};save()}}}});
const c=document.querySelector(`[data-cause="${{id}}"]`);c.value=s.cause||"";
c.onchange=()=>{{store[id]={{...store[id],cause:c.value}};save()}};
const t=document.querySelector(`[data-note="${{id}}"]`);t.value=s.note||"";
t.oninput=()=>{{store[id]={{...store[id],note:t.value}};save()}}}}
document.getElementById("export").onclick=()=>{{const q=v=>'"'+String(v||"").replace(/"/g,'""')+'"';
const rows=["sample_id,label,false_alarm_cause,note"];for(const id of IDS){{const s=store[id]||{{}};
rows.push([id,s.label,s.cause,s.note].map(q).join(","))}}
const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([rows.join("\\n")],{{type:"text/csv"}}));
a.download="validation_labels.csv";a.click()}};refresh();
</script></body></html>"""
    out = p.results / "validation_helper.html"
    out.write_text(page, "utf-8")
    log.info("labeling helper -> %s", out)
    return out


def write_review_table(cfg: Config, parcel_money: gpd.GeoDataFrame, top: int = 50) -> Path:
    """Write ``results/review.html``: flagged parcels ranked by estimated yearly tax (F12).

    Args:
        cfg: Loaded config.
        parcel_money: Parcel changes with ``rank`` and ``est_yearly_tax_usd``.
        top: Number of top-ranked parcels to include.

    Returns:
        Path of the HTML file. Private: never deployed.
    """
    p = Paths(cfg.root)
    flagged = parcel_money[parcel_money["rank"].notna()].sort_values("rank").head(top)
    flagged = flagged.assign(key=[f"R{int(r):03d}" for r in flagged["rank"]])
    write_chips(cfg, flagged, "key", p.results / "chips" / "review")
    rows = []
    for _, r in flagged.iterrows():
        kinds = [(k, int(r[f"n_{k}"])) for k in ("new", "expanded", "demolished") if r[f"n_{k}"]]
        glyph = {"new": "■", "expanded": "◧", "demolished": "□"}
        change = ", ".join(f"{glyph[k]} {n} {k}" for k, n in kinds)
        rows.append(
            f"<tr><td class='mono'>{int(r['rank'])}</td><td class='mono'>{html.escape(str(r['parcel_id']))}"
            f"</td><td>{change}</td><td class='num mono'>{r['added_sqft']:,.0f}</td>"
            f"<td class='num mono'>{int(r['n_permits'])}</td>"
            f"<td class='num mono'>${r['est_yearly_tax_usd']:,.0f}</td>"
            f"<td><img src='chips/review/{r['key']}_before.png' alt='before'></td>"
            f"<td><img src='chips/review/{r['key']}_after.png' alt='after'></td>"
            "<td><select><option></option><option>Confirmed</option><option>False alarm</option>"
            "<option>Unsure</option></select></td><td><input type='text'></td></tr>"
        )
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parcel Review Table</title><style>{_CSS}</style></head><body>
<header><h1>ParcelWatch · private review table</h1><span class="muted">Top {len(flagged)}
flagged parcels by estimated yearly tax (raw, not precision-adjusted). Private: never publish.
Flags are leads from aerial imagery, not findings.</span></header><main><table><thead><tr>
<th>Rank</th><th>Parcel ID</th><th>Change</th><th class="num">Added sq ft</th>
<th class="num">Permits in window</th><th class="num">Est. yearly tax</th>
<th>{cfg.imagery.before.year}</th><th>{cfg.imagery.after.year}</th><th>Verdict</th><th>Note</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></main></body></html>"""
    out = p.results / "review.html"
    out.write_text(page, "utf-8")
    return out


def label_spot_check(cfg: Config, n: int | None = None, cols: int = 10) -> Path:
    """Draw ``n`` random Overture buildings on the After image as one contact sheet.

    Used to spot-check training labels before v1 training (``model.v1.label_spot_check``).

    Args:
        cfg: Loaded config.
        n: Number of labels (defaults to the config value).
        cols: Chips per row.

    Returns:
        Path of ``results/figures/overture_spot_check.png``.
    """
    from PIL import Image, ImageDraw

    p = Paths(cfg.root)
    n = n or cfg.model.v1.label_spot_check
    ov = gpd.read_file(p.overture_clipped)
    pick = ov.sample(n=min(n, len(ov)), random_state=cfg.model.seed).reset_index(drop=True)
    size = 128
    rows = (len(pick) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * size, rows * (size + 14)), "white")
    tmp = p.results / "chips" / "spot"
    for i, geom in enumerate(pick.geometry):
        f = render_chip(p.naip_after_aligned, geom, tmp / f"L{i + 1:02d}.png", px=size)
        r, c = divmod(i, cols)
        sheet.paste(Image.open(f), (c * size, r * (size + 14) + 14))
        ImageDraw.Draw(sheet).text(
            (c * size + 3, r * (size + 14) + 1), f"L{i + 1:02d}", fill="black"
        )
    out = p.results / "figures" / "overture_spot_check.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
