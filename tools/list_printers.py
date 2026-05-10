"""Print every printer Windows currently knows about.

Run this first so you can see exactly how Windows names the BTP-L560
after you install it. Copy that name into print_test.py.
"""
import win32print

for flag, desc, name, comment in win32print.EnumPrinters(
    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
):
    print(name)
