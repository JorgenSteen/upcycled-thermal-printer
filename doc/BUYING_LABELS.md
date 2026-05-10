# Buying replacement label rolls for the BTP-L560

A focused checklist for shopping. For setup, calibration, and the wider
context, see `RECIPE.md`.

## Hard spec — what fits the L560

| Field | Required value |
|---|---|
| **Coating** | **Direct thermal** (DT / *direkte termisk* / *thermo direct*). **NOT** thermal transfer (TT / *thermo transfer*) — the L560 has no ribbon mechanism, so TT prints come out blank. |
| **Liner width** | 60 or 62 mm |
| **Label face width** | ≤ 56 mm (the print head width) |
| **Label height** | 30–100 mm is the practical range. < ~20 mm is too short for the gap sensor; > ~100 mm gets memory-tight. |
| **Detection** | **Gap-detect** is the standard generic format and works on the L560's transmissive sensor. Plain die-cut self-adhesive labels with visible gaps in the listing photos = good. |
| **Core inner diameter** | **25 mm (1″)** is the OEM spool size. 40 mm cores need a 3D-printed adapter (see `RECIPE.md`). Anything < 25 mm won't fit. |
| **Roll outer diameter** | ≤ 80 mm |
| **Adhesive** | Permanent (unless you actually want repositionable) |

## Avoid these (won't work)

- **Thermal transfer / TT / *thermo transfer*** — needs a ribbon the L560 doesn't have.
- **Linerless** — needs a special non-stick platen the L560 doesn't have.
- **Dymo LabelWriter cartridges** — proprietary, not roll-on-spool.
- **Brother QL DK rolls** — proprietary.
- **Width 80 mm or 100 mm** — won't fit the 62 mm paper path.
- **Pure black-mark detection (no gaps)** — works in theory, but most cheap rolls are gap-only; gap-detect is safer to bet on.

## Search strings

### AliExpress (cheapest, slow ship)

Use the tightest one that matches your size choice:

- `60mm direct thermal label 25mm core gap`
- `60x40 direct thermal label roll`
- `58mm direct thermal sticker roll`
- `direct thermal label 25mm core 1 inch`

Tick filters for "Direct Thermal" in the sidebar if available. **Always
read the Specifications table** before buying — confirm DT, width, core
diameter. If a field is missing, message the seller: *"Is this direct
thermal? What is the core inner diameter in mm?"* They usually reply within
a day.

### Norwegian retailers

- [etikettlageret.no — thermoetiketter](https://www.etikettlageret.no/labels-til-etikettskriver/thermoetiketter)
- [taelektronikk.no — thermo etiketter](https://www.taelektronikk.no/produkter/etiketter/thermo-etiketter)
- [kontorproffen.no — termo etiketter på rull](https://www.kontorproffen.no/1110-termo-etiketter-pa-rull)
- [es.no (Etikett Systemer)](https://www.es.no/nettbutikk/36-lagerfoerte-thermoetiketter-paa-rull-for-etikettskriver/)

What's actually been verified in stock (as of writing):

| Retailer | Product | Width × Height | Core | Caveat |
|---|---|---|---|---|
| etikettlageret.no | Thermo ECO Basic 60×10 mm (2,500 stk) | 60 × 10 mm | not listed | **Too short** for title + body. Good for tiny barcode/price stickers only. |
| etikettlageret.no | Thermo ECO Basic 60×15 mm (2,500 stk) | 60 × 15 mm | not listed | Borderline short. One-line labels. |
| taelektronikk.no | Standard HR10 60×40 mm | 60 × 40 mm | **40 mm** | **Core too big for the 25 mm OEM spool — needs a 3D-printed adapter** (see RECIPE.md). |
| taelektronikk.no | Standard VF10 60×22 mm | 60 × 22 mm | **40 mm** | Same core issue. |
| taelektronikk.no | Standard VF10 58×100 mm | 58 × 100 mm | **40 mm** | Same core issue + tall label. |

If none of these fit cleanly, **email etikettlageret.no** with the spec —
they custom-cut rolls. Norwegian email body:

> Hei, jeg trenger termoetiketter på rull med følgende spesifikasjon:
> 60 mm bredde, 40 mm høyde, direkte termisk, gap-deteksjon, 25 mm
> kjernediameter, maks 80 mm rulldiameter, permanent lim. Hva koster det?

## Verifying a specific listing

Paste these into any listing's spec table and check:

1. ✅ "Direct thermal" / "DT" / "Thermal direct" — not "thermal transfer".
2. ✅ Width 58 or 60 mm.
3. ✅ Core 25 mm (1″) — or 40 mm if you'll print an adapter.
4. ✅ Gap-detect (or just standard die-cut self-adhesive labels with visible gaps).
5. ✅ Permanent adhesive.
6. ✅ Roll OD ≤ 80 mm.

Photos should show a roll of distinct labels with gaps between them on a
glassine (waxy) backing — not a solid continuous strip (continuous works
too, but isn't pre-cut into stickers).

## After loading a new roll

1. Power off, load roll, close cover.
2. Hold **FEED**, flip power on. Release FEED when paper feeds.
3. Short-press **FEED 3×**, then hold **FEED ≥ 1 sec** — runs label calibration.
4. In `label_gui.py`, set `LABEL_FEED_MM` to roughly the new label height
   (e.g. `40` for 60×40 mm labels).
