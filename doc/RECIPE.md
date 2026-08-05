# Alere BTP-L560 → Python printing

Repurposing a retired Alere Universal Printer (SNBC BTP-L560 thermal label
printer) so any Python script can print to it.

## What this printer is

- **Maker:** SNBC / Beiyang. Alere just rebadges it.
- **Command language:** ESC/POS (*not* TSPL like most label printers — this is
  why label-printer software produced garbage previously).
- **Connection:** USB-B + RS-232 serial.
- **Resolution / width:** 203 DPI, 56 mm print width (~448 dots), 62 mm paper.
- **Built-in barcodes:** UPC, EAN, CODE128, PDF417, QR, etc. Use the printer's
  native renderers for these — bitmap rendering needs a profile width set or
  it falls back silently.

## Step 1 — print the self-test (no PC needed)

Confirms the hardware works and shows the current settings.

1. Power off. Load a label roll, close the cover.
2. Hold **FEED**, flip power **on**.
3. When paper starts feeding, release FEED.
4. Short-press FEED once → it prints the config page.

The line that matters is `Interface Mode: WinDriver Mode`. That means the
printer enumerates as a normal Windows printer and we can drive it through the
print spooler. (The other option is `API Mode`, which would need libusb/pyusb.)

## Step 2 — install in Windows

If a previous install left a "ghost" printer (no real USB binding behind it),
delete it first: *Settings → Printers & scanners → \[ghost\] → Remove*.

1. Plug in USB. Open *Device Manager* — the printer should appear under
   *Universal Serial Bus controllers* / similar, even if Windows doesn't have
   a driver for it.
2. *Settings → Printers & scanners → Add device → "The printer I want isn't
   listed" → Add a local printer with manual settings*.
3. **Port:** pick the `USBxxx` entry that's labeled "Unknown printer" — that
   is the L560.
4. **Driver:** *Generic → Generic / Text Only*. (Or install the Seagull SNBC
   BTP-L540 BPLE driver if you want a real driver — both work because we send
   raw ESC/POS bytes that bypass driver rendering.)
5. Name it (e.g. `BTP-L560`). Don't share. Skip the Windows test page (that
   driver's test page prints a label of garbage). Finish.
6. From the printer's properties, **Print Test Page** to confirm the path
   works end-to-end before involving Python.

## Step 3 — Python

```powershell
pip install -r requirements.txt
python tools/list_printers.py     # find the exact name Windows uses
# edit PRINTER_NAME in tools/print_test.py to match
python tools/print_test.py
```

Files:

- `requirements.txt` — `python-escpos` + `pywin32` + `Pillow` + `qrcode`
- `flex_label.py` — the GUI app
- `tools/list_printers.py` — enumerates installed Windows printers
- `tools/print_test.py` — minimal hello-world: text, separator, native QR
- `tools/check_queue.py` — prints printer status flags + pending jobs (debugging)

## Tunable settings

`flex_label.py` exposes everything tunable through **Settings** in the GUI
(menu bar → Settings → Open Settings…):

| Setting | Default | What to do if it's off |
|---|---|---|
| Printer name | `BTP-L560` | Match the name in `tools/list_printers.py` output. |
| Trailing feed (mm) | `70` | Tear edge stops short of the tear bar → raise it. Wastes a blank label between prints → lower it. Implemented via `ESC J` (1 dot = 1/203 inch). |
| Leading feed (mm) | `0` | Set positive if content lands too high on the sticker. |
| Default font / size | Arial / 12 pt | Applied to *new* text blocks; existing blocks keep their own size. |

Per-document knobs (tape width, usable width, sticker height, copies, gap)
live on the front panel.

## Sticker labels — what to buy

> For a focused buying checklist (search strings, spec table, retailer notes),
> see **`BUYING_LABELS.md`**.


Spec from the manual (Appendix 1.2): **62 mm liner / 56 mm label face / 70 mm
label height, direct thermal, with a 3 × 8 mm detection hole 7 mm from the
edge of the liner.** This is *not* a gap-detect format — generic
56 × 70 mm thermal labels probably won't auto-align without recalibration.

Best bets for matching rolls (no mode switching needed):

- **OEM Alere part number: `14-716AFI`** — sometimes listed as "Alere Thermal
  Printer Labels Roll" or "Alere Universal Printer labels". Sold through:
  - [Amazon (PN 14-716AFI)](https://www.amazon.com/Alere-Thermal-Printer-Universal-14-716afi/dp/B00D639DC4)
  - [McKesson item 841594](https://mms.mckesson.com/product/841594/Abbott-Rapid-Dx-North-America-LLC-26333) — listed under Abbott Rapid Dx (Abbott bought Alere).
  - [CleanItSupply](https://www.cleanitsupply.com/p-252700/alere-thermal-printer-labels-1-each-841594_ea.aspx)
  - [Suprememed](https://www.suprememed.com/thermal-printer-labels-alere-roll-white-55-mm/) (their listing says 55 mm but it's the same OEM roll)
- **Search terms that hit the right format:**
  - `"Alere Universal Printer labels"`
  - `"Alere thermal printer labels 14-716AFI"`
  - `"Alere INRatio labels"` or `"Alere Triage labels"` (the original test devices
    used the same printer)
  - `"Abbott Rapid Dx 841594"` (post-acquisition listings)

If you only ever want to print custom stuff (not stickers), 58 mm direct
thermal **continuous receipt rolls** (POS receipt paper) fit and are far
cheaper. Search `"58 mm thermal POS receipt roll 80 mm OD"`. No detection
hole needed — printer treats it as continuous paper.

### Generic stickers (cheaper than OEM)

The L560 has a fixed transmissive sensor (same as the L540). It detects the
OEM punched hole, **but it also detects plain gaps between labels** — which
is the standard generic format. So generic gap-detect direct thermal labels
work, you just need to recalibrate after loading.

What to look for:

- **Label face**: 56-58 mm. **Liner**: 60 or 62 mm.
- **Coating**: direct thermal (no ribbon).
- **Detection**: gap-detect (don't bother with punched-hole-specific stock).
- **Core**: 1″ (25 mm). **Max OD**: 80 mm.
- **Height**: anything (40/50/60/70/100 mm common). Set the matching
  Sticker height on the front panel and the Trailing feed in Settings.

Search terms (cheap, in order of hit-rate):

- `58mm thermal label roll direct thermal`
- `60mm x 40mm direct thermal labels`
- `2.28 inch direct thermal labels` (US listings)

Examples: [Make Me A Label 58×60](https://makemealabel.com/products/58mm-x-60mm-direct-thermal-labels),
[Make Me A Label 58×40](https://makemealabel.com/products/copy-of-58mm-x-60mm-direct-thermal-roll-labels),
[Amazon iDPRT 58×30](https://www.amazon.com/iDPRT-Thermal-Multi-Purpose-Self-Adhesive-Compatible/dp/B09Y5XQX3M).

**Recalibration after switching labels** (manual §2.5.3):

1. Power off, load new roll, close cover.
2. Hold **FEED**, flip power on. Release FEED when paper feeds.
3. Short-press **FEED 3×**, then hold **FEED ≥ 1 sec**.
4. Printer feeds a few labels, learns the new gap. Done.

## Gotchas we hit

- **`AttributeError: 'Win32Raw' object has no attribute 'feed'`** — python-escpos
  uses `p.ln(n)` (or `p.text("\n" * n)`), not `feed()`.
- **Warning: `media.width.pixel field of the printer profile is not set`** —
  fires when bitmap-rendered output is asked to center. Either set the profile,
  or use `p.qr(..., native=True)` which uses the printer's built-in QR engine
  and skips bitmap rendering entirely.
- **Script "succeeds" but nothing prints** — check the print queue for stuck
  jobs (`check_queue.py` or *Open print queue* in the Settings panel). Also
  make sure the printer name in the script matches a real, currently-bound
  device, not a leftover ghost from a previous install.
- **CR is disabled by default** on this printer — sending plain text with
  `\r\n` line endings won't break lines correctly. Use `\n` only.
- **USB port-binding** — the Windows printer queue is bound to a specific
  `USBnnn` port (whichever was active at install). If you plug into a
  different physical USB port, the queue points at empty USB003 and prints
  silently fail. Either always use the same port (sticker the port), or go
  to *Printer properties → Ports* and tick the new `USBxxx` after switching.
  Find which port the printer is actually on with PowerShell:
  `Get-PnpDevice | Where-Object { $_.InstanceId -like 'USBPRINT*' }` — the
  entry with Status `OK` is the live one — then
  `Set-Printer -Name "BTP-L560" -PortName "USBnnn"`.
  **Also check the offline flag**: while the queue pointed at a dead port,
  Windows silently sets *Use Printer Offline* on it, and this persists after
  the port is fixed — jobs then spool and sit in the queue forever. Untick it
  in the queue window (*Printer* menu), or clear attribute bit `0x400` via
  `win32print.SetPrinter`. Verify the fix with `python tools/feed_test.py`:
  the paper should advance and `check_queue.py` should show 0 pending jobs.
  The proper fix is direct USB via libusb (requires the printer's
  `Interface Mode` to be flipped from `WinDriver Mode` to `API Mode` via the
  FEED-button menu — see manual Appendix 3).
- **`p.ln(3)` is way too little for a 70 mm label** — it feeds ~12 mm, leaving
  most of the just-printed sticker still inside the printer. Use mm-based
  feed via `ESC J` (`_feed_mm()` helper in `flex_label.py`). Default 70 mm
  pushes one full label past the tear bar.
- **Bitmap centring needs `media.width.pixel`** — `p.set(align="center")` plus
  bitmap-rendered content (default `qr()`, raster images) emits a warning and
  doesn't actually centre. Use native QR (`qr(..., native=True)`) or set the
  profile width.

## Useful references

- [Alere Universal Printer User Manual (PN 55115)](https://stat-technologies.com/wp-content/uploads/2018/12/Alere-Universal-Printer-User-Manual.pdf)
- [SNBC BTP-L540 BPLE Windows driver (Seagull)](https://www.seagullscientific.com/downloads/printer-drivers/snbc-btp-l540-bple/)
- [python-escpos docs](https://python-escpos.readthedocs.io/)
