"""Feed-only test: send ESC J at a known mm, no printing.

Use this to confirm whether the printer's actual paper advance matches
what we asked for. The GUI's "Trailing feed (mm)" setting uses the same
ESC J primitive — if this script's output matches the requested amount,
the GUI's feed control is honest, and any extra feed you see must come
from elsewhere (Windows driver form-feed, the printer's own
gap-detect auto-advance, etc).

Procedure:
  1. Edit PRINTER_NAME below if yours differs.
  2. Edit TEST_MM. Start small — 10 mm. Keep it ≤ 30 so you don't waste
     a sticker per run.
  3. Mark the current paper edge with a pen.
  4. python tools/feed_test.py
  5. Measure from your pen mark to the new paper edge.
  6. Compare to TEST_MM. Within ~1 mm = good. Way off = printer or
     driver is overriding our command.
  7. Re-mark edge, change TEST_MM, repeat.

Suggested run sequence (totals 60 mm = under one sticker):
  TEST_MM = 10   → measure
  TEST_MM = 20   → measure
  TEST_MM = 30   → measure
"""
from escpos.printer import Win32Raw

PRINTER_NAME = "BTP-L560"
TEST_MM = 20            # change between runs; suggest 10 then 20 then 30

DOTS_PER_MM = 203 / 25.4   # 203 DPI print head


def main() -> None:
    p = Win32Raw(printer_name=PRINTER_NAME)
    try:
        dots = int(TEST_MM * DOTS_PER_MM)
        chunks = 0
        while dots > 0:
            chunk = min(dots, 255)   # ESC J takes one byte (0..255 dots)
            p._raw(b"\x1bJ" + bytes([chunk]))
            dots -= chunk
            chunks += 1
        print(f"Sent ESC J for {TEST_MM} mm "
              f"({int(TEST_MM * DOTS_PER_MM)} dots, {chunks} chunk(s)).")
        print("Measure from your pen mark to the new paper edge.")
    finally:
        p.close()


if __name__ == "__main__":
    main()
