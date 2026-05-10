"""Minimal print test for the Alere BTP-L560 (SNBC, ESC/POS).

Sends raw ESC/POS bytes through the Windows print spooler. The printer
just has to be installed in Windows under SOME driver — even
"Generic / Text Only" works, because Win32Raw bypasses the driver's
rendering and dumps the bytes straight to the device.

Steps:
  1. pip install -r requirements.txt
  2. python list_printers.py   # find the exact name Windows uses
  3. Edit PRINTER_NAME below
  4. python print_test.py
"""
from escpos.printer import Win32Raw

PRINTER_NAME = "Alere BTP-L560"

LINE_WIDTH = 37  # font A at 56 mm print width


def main() -> None:
    p = Win32Raw(printer_name=PRINTER_NAME)

    p.set(align="center", bold=True, double_height=True)
    p.text("Hello, world!\n")

    p.set(align="center")
    p.text("Hei fra Python\n")
    p.text("-" * LINE_WIDTH + "\n")

    p.set(align="left")
    p.text("This printer is repurposed.\n")
    p.text("It used to print test results.\n")
    p.text("Now it prints whatever you want.\n\n")

    p.set(align="center")
    p.qr("https://example.com", size=6, native=True)

    p.ln(3)
    p.close()


if __name__ == "__main__":
    main()
