# upcycled-thermal-printer

Give a retired thermal label printer a second life. A small Python GUI for
designing and printing custom labels on **ESC/POS** thermal printers. Built
around an **Alere Universal Printer / SNBC BTP-L560** rebadged from a
discontinued medical device, but works with most ESC/POS thermal label or
receipt printers.

## Why

The Alere / Abbott Rapid Dx thermal printers were discontinued along with the
diagnostic devices that shipped them — perfectly good 203 DPI thermal printers
ending up as e-waste. They speak ESC/POS over USB and will happily print
whatever bytes you send them. This repo is the GUI on top of `python-escpos`
so you don't have to.

If you have a similar retired thermal label printer (SNBC, Alere, Abbott, an
old POS receipt printer, generic ESC/POS thermal label printer), you can
either:

- **Run this app as-is** — set the printer name and feed mm in Settings.
- **Copy the rendering pipeline** out of `flex_label.py` — it's a self-
  contained PIL → `p.image()` bitmap path that sidesteps every common
  ESC/POS gotcha (font A/B limits, integer-only multipliers, the
  `media.width.pixel` centring warning, dithered text on receipt media, etc).

## What it does

- **Block-based label designer** — stack text blocks (per-block font, size,
  bold, alignment), QR codes, spacers, dashed cut markers
- **Live WYSIWYG preview** — exactly what gets printed, scaled to the
  printer's native 203 DPI
- **Sticker boundary outline** — set your sticker height (e.g. 60 mm) and the
  preview draws a red dashed rectangle around each sticker so you can see how
  content fits a die-cut label
- **Multi-copy / fill-to-length** — print N copies in one job, or "fit as many
  as possible in 200 mm of tape", scissor them apart afterwards
- **Save / load presets** as JSON
- **Settings menu** — printer name, leading / trailing feed, default font,
  default text size

## Keywords

ESC/POS · thermal label printer · thermal receipt printer · BTP-L560 · SNBC
Beiyang · Alere Universal Printer · Abbott Rapid Dx · 14-716AFI · McKesson
841594 · INRatio · Triage · repurposed printer · upcycled e-waste · Python
tkinter · python-escpos · Win32Raw · label designer · QR code labels ·
die-cut labels · direct thermal · gap-detect · 203 DPI · Pillow PIL bitmap
rendering · `p.image()` · `ESC J` paper feed.

## Setup

Full Windows install walkthrough is in **[`doc/RECIPE.md`](doc/RECIPE.md)**.
TL;DR:

```powershell
pip install -r requirements.txt
python tools/list_printers.py        # confirm the exact Windows printer name
python flex_label.py
```

For label rolls that fit, see **[`doc/BUYING_LABELS.md`](doc/BUYING_LABELS.md)**.

## Tools (`tools/`)

These three helpers are not part of the GUI but are useful for setup and
debugging the print path.

| Script | Run when |
|---|---|
| **`tools/list_printers.py`** | Once after install — enumerates every printer Windows currently knows about, so you can copy the exact queue name into Settings. |
| **`tools/print_test.py`** | After installing the driver, before launching the GUI — sends a hard-coded "Hello world" with text + dashed line + native QR. If this prints, the spooler path works end to end. |
| **`tools/check_queue.py`** | When prints "succeed" but nothing comes out — dumps the printer's status flags (PAPER_OUT, OFFLINE, USER_INTERVENTION, etc.) and any pending jobs in the queue. |

Edit the `PRINTER_NAME` constant at the top of `print_test.py` /
`check_queue.py` to match your install before running.

## Where things go at runtime

- `presets/` — your saved label designs, one JSON file per preset. Auto-
  created next to the script. Gitignored — per-machine.
- `flex_label_settings.json` — printer name, feed mm, default font / size.
  Gitignored.

## Compatibility

Speaks ESC/POS over the Windows print spooler via `python-escpos`'s
`Win32Raw`. Any ESC/POS printer that accepts raw bytes and renders bitmaps
via `GS v 0` or `ESC *` should work; you'll likely just need to retune
**Trailing feed (mm)** and **Tape width (mm)** in Settings. If `p.image()`
silently fails, swap `impl="bitImageColumn"` to `"graphics"` or
`"bitImageRaster"` in `print_doc()` — different printers prefer different
raster impls.

The GUI and preview also run on Linux / macOS for development — only the
`Print` button needs Windows.
