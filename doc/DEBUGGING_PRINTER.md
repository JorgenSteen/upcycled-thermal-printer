# Debugging & Adding the Printer (BTP-L560 on Windows)

Practical recipe for the common Windows printer headaches with the BTP-L560.
All commands are PowerShell on the Windows host (run as Admin), not WSL.

---

## 1. Ghost printer — UI says it's gone but `Add Printer` says "name taken"

**Symptom:** printer doesn't show in Settings, Control Panel, or Device Manager
(even with *Show hidden devices*), but you can't re-add it under the same name
because Windows says the name is already in use.

### Diagnose

```powershell
Get-Printer       | Format-Table Name, PortName, DriverName, PrinterStatus
Get-PrinterPort   | Format-Table Name, Description
Get-PrinterDriver | Format-Table Name, Manufacturer
```

Find the row matching `BTP-L560` / `Alere` / `Generic / Text Only`.

### Remove

```powershell
Remove-Printer -Name "BTP-L560"
```

If that errors with *in use* / *access denied*, clear the spool queue first:

```powershell
Stop-Service Spooler -Force
Remove-Item "$env:SystemRoot\System32\spool\PRINTERS\*" -Force
Start-Service Spooler
Remove-Printer -Name "BTP-L560"
```

Verify:

```powershell
Get-Printer | Where-Object Name -Match "BTP|Alere"   # expect empty
```

### Stuck non-BTP entry (e.g. "Generic / Text Only")

Same approach. If it's set as default, `Remove-Printer` may refuse — first
demote it via *Settings → Printers → manage*, then retry. Spooler restart
above clears most "in use" errors.

---

## 2. Ghost `USB00n` ports in *Print Server Properties → Ports*

**Symptom:** USB001…USB005 accumulate over time, can't be deleted from the UI
("port is in use"), persist even when nothing is plugged in.

**Cause:** Windows' USB Print Monitor keys each port to a physical USB socket's
hardware ID. `Remove-PrinterPort` can't see them — it queries the wrong monitor
and fails with `HRESULT 0x80070002` (file not found).

### Cleanest removal — uninstall ghost USB device records

In an Admin **cmd** (the env var trick only works in cmd):

```cmd
set DEVMGR_SHOW_NONPRESENT_DEVICES=1
devmgmt.msc
```

Then *View → Show hidden devices*. Look under:

- **Printers** — greyed-out entries
- **Universal Serial Bus controllers** → greyed **USB Printing Support**

Right-click → **Uninstall device**. Do **not** tick *Delete the driver software*.
Reboot. The freed USB00n entries should be gone (USB001 stays — Windows will
reuse it on next plug-in).

### If Device Manager is already clean but ports persist

Cosmetic only — they're inert. No driver, no device, no printer references
them. Safe to leave. Going forward: **always plug into the same physical USB
socket** so you don't grow more.

Registry path (only if a stale entry actively conflicts):
`HKLM\SYSTEM\CurrentControlSet\Control\Print\Monitors\USB Monitor\Ports`.
Read first, never blind-edit.

---

## 3. Adding the printer fresh

### Step 1 — Baseline snapshot (before plugging in)

```powershell
$before = Get-PrinterPort | Where-Object Name -Match '^USB'
$before | Format-Table Name, Description
```

### Step 2 — Plug in, wait ~5 sec, snapshot again

```powershell
$after = Get-PrinterPort | Where-Object Name -Match '^USB'
$after | Format-Table Name, Description
Compare-Object $before.Description $after.Description
```

**Note:** the BTP-L560 reuses the same `USB00n` as the physical socket it was
last plugged into — if you stick to the same socket, the port list won't
visibly change. That's fine. The real check is hardware presence (step 3).

### Step 3 — Confirm hardware enumeration

```powershell
Get-PnpDevice -PresentOnly |
  Where-Object InstanceId -Match 'USBPRINT' |
  Format-Table FriendlyName, Status, InstanceId
```

Expected output:

```
FriendlyName        Status InstanceId
------------        ------ ----------
No Printer Attached OK     USBPRINT\UNKNOWNPRINTER\...\USB00X
```

- `FriendlyName = "No Printer Attached"` and `UNKNOWNPRINTER` are **normal**
  for the BTP-L560 — its firmware doesn't report clean USB product strings,
  but the print class enumerates correctly.
- The trailing `USB00X` is the port to use.
- Verify it's not a ghost by unplugging and re-running — the row should
  disappear, then reappear when plugged back in.

### Step 4 — Add the printer

```powershell
Add-Printer -Name "BTP-L560" -DriverName "Generic / Text Only" -PortName "USB004"
Get-Printer -Name "BTP-L560" | Select Name, PortName, DriverName, PrinterStatus
```

Adjust `USB004` to whatever step 3 showed. `PrinterStatus = Normal` = ready.

### Step 5 — Test print

Use `flex_label/tools/print_test.py` for a minimal ESC/POS verification
(no big paper burn).

---

## Driver / mode notes

- **Driver:** Generic / Text Only — pass-through, doesn't try to rasterize.
  Correct for `python-escpos` with the `Win32Raw` backend.
- **Printer Interface Mode:** WinDriver Mode (check via FEED-button self-test).
  API Mode would bypass the Windows spooler entirely — not what we use here.
- **Port stability:** Plugging into a different physical USB socket silently
  breaks printing — the queue is bound to the port. Either same socket every
  time, or repoint the queue under *Printer properties → Ports*.
