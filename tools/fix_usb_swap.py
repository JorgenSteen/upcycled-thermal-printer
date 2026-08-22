r"""One-shot fix for the BTP-L560 after a USB plug swap.

When the printer is plugged into a different physical USB port, two things
break (see doc/RECIPE.md "USB port-binding"):

  1. The Windows queue stays bound to the old, now-dead `USBnnn` port, so
     jobs silently go nowhere.
  2. While the port was dead, Windows silently set the *Use Printer Offline*
     attribute (bit 0x400) — and it persists after the port is fixed, so
     jobs spool and sit in the queue forever.

This script finds the live USBPRINT device, rebinds the queue to its port,
and clears the offline flag. Verify afterwards with:

    python tools\feed_test.py     (paper should advance)
    python tools\check_queue.py   (queue should drain to 0 jobs)
"""
import re
import subprocess
import sys

import win32print

PRINTER_NAME = "BTP-L560"
OFFLINE_BIT = 0x400


def find_live_usb_port() -> str:
    """Return the USBnnn port of the one USBPRINT device with Status OK."""
    out = subprocess.check_output(
        [
            "powershell", "-NoProfile", "-Command",
            "Get-PnpDevice | Where-Object { $_.InstanceId -like 'USBPRINT*' }"
            " | ForEach-Object { \"$($_.Status)`t$($_.InstanceId)\" }",
        ],
        text=True,
    )
    live = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status, instance_id = line.split("\t", 1)
        m = re.search(r"(USB\d+)$", instance_id.strip())
        if status.strip() == "OK" and m:
            live.append(m.group(1))
    if len(live) == 1:
        return live[0]
    if not live:
        sys.exit("No USBPRINT device with Status OK found — is the printer "
                 "plugged in and powered on?")
    sys.exit(f"Multiple live USBPRINT ports found ({', '.join(live)}) — "
             f"rebind manually with Set-Printer -Name \"{PRINTER_NAME}\" "
             "-PortName <port>.")


def main() -> None:
    port = find_live_usb_port()

    h = win32print.OpenPrinter(
        PRINTER_NAME, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
    try:
        info = win32print.GetPrinter(h, 2)
        changed = False

        if info["pPortName"] != port:
            print(f"Rebinding port: {info['pPortName']} -> {port}")
            info["pPortName"] = port
            changed = True
        else:
            print(f"Port already bound to {port}")

        if info["Attributes"] & OFFLINE_BIT:
            print(f"Clearing offline flag "
                  f"(attributes 0x{info['Attributes']:X} -> "
                  f"0x{info['Attributes'] & ~OFFLINE_BIT:X})")
            info["Attributes"] &= ~OFFLINE_BIT
            changed = True
        else:
            print("Offline flag not set")

        if changed:
            # SetPrinter rejects the security descriptor GetPrinter returns;
            # None means "leave it unchanged".
            info["pSecurityDescriptor"] = None
            win32print.SetPrinter(h, 2, info, 0)
            print("Done. Verify with: python tools\\feed_test.py")
        else:
            print("Nothing to fix.")
    finally:
        win32print.ClosePrinter(h)


if __name__ == "__main__":
    main()
