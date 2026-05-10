"""Show printer status + any pending jobs for the BTP-L560."""
import win32print

PRINTER_NAME = "Label Printer 1"

STATUS_FLAGS = {
    0x00000001: "PAUSED",
    0x00000002: "ERROR",
    0x00000004: "PENDING_DELETION",
    0x00000008: "PAPER_JAM",
    0x00000010: "PAPER_OUT",
    0x00000020: "MANUAL_FEED",
    0x00000040: "PAPER_PROBLEM",
    0x00000080: "OFFLINE",
    0x00000100: "IO_ACTIVE",
    0x00000200: "BUSY",
    0x00000400: "PRINTING",
    0x00000800: "OUTPUT_BIN_FULL",
    0x00001000: "NOT_AVAILABLE",
    0x00002000: "WAITING",
    0x00004000: "PROCESSING",
    0x00008000: "INITIALIZING",
    0x00010000: "WARMING_UP",
    0x00020000: "TONER_LOW",
    0x00040000: "NO_TONER",
    0x00080000: "PAGE_PUNT",
    0x00100000: "USER_INTERVENTION",
    0x00200000: "OUT_OF_MEMORY",
    0x00400000: "DOOR_OPEN",
    0x00800000: "SERVER_UNKNOWN",
    0x01000000: "POWER_SAVE",
}

h = win32print.OpenPrinter(PRINTER_NAME)
info = win32print.GetPrinter(h, 2)
status = info["Status"]
print(f"Driver:  {info['pDriverName']}")
print(f"Port:    {info['pPortName']}")
print(f"Status:  0x{status:08x}", end="")
flags = [name for bit, name in STATUS_FLAGS.items() if status & bit]
print(f"  ({', '.join(flags) if flags else 'READY'})")

jobs = win32print.EnumJobs(h, 0, 999, 1)
print(f"Jobs in queue: {len(jobs)}")
for j in jobs:
    print(f"  - id={j['JobId']}  doc={j['pDocument']}  status={j['Status']}  pages={j['TotalPages']}")
win32print.ClosePrinter(h)
