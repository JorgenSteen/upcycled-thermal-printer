"""Flex Label — block-based label designer for the Alere BTP-L560.

Standalone Tk app, separate from the original `label_gui.py`. Per-block
formatting (text size/bold/align), QR codes, spacers, and dashed cut-markers
for multi-label-per-tape workflows. Live preview via PIL bitmap rendering;
the same image is what gets sent to the printer, so preview == output.

Run on Windows. On Linux/WSL the GUI launches and previews work, but Print
will fail because Win32Raw is Windows-only.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Union

import qrcode
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageDraw, ImageFont, ImageTk

try:
    from escpos.printer import Win32Raw
except ImportError:
    Win32Raw = None  # GUI still runs; Print action errors out cleanly.


DOTS_PER_MM = 203 / 25.4         # 203 DPI print head
PT_TO_DOTS = 203 / 72            # ≈ 2.82 dots per point
MAX_PRINT_WIDTH_DOTS = 448       # 56 mm @ 203 DPI
PREVIEW_ZOOM = 1

ALIGN_OPTIONS = ("left", "center", "right")

FONT_FAMILIES = (
    "Arial",
    "DejaVu Sans",
    "Comic Sans MS",
    "Century Gothic",
    "Old English Text",
    "Impact",
)

SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = SCRIPT_DIR / "flex_label_settings.json"
PRESETS_DIR = SCRIPT_DIR / "presets"


# --------------------------------------------------------------------------- #
# Model                                                                       #
# --------------------------------------------------------------------------- #

@dataclass
class TextBlock:
    text: str = ""
    size_pt: int = 12
    bold: bool = False
    align: str = "left"

    def summary(self) -> str:
        first_line = self.text.splitlines()[0] if self.text else ""
        snippet = first_line[:24] + ("…" if len(first_line) > 24 else "")
        bold = " bold" if self.bold else ""
        return f'Text "{snippet}" · {self.size_pt}pt{bold} · {self.align}'


@dataclass
class QRBlock:
    data: str = ""
    size_mm: float = 18.0
    align: str = "center"

    def summary(self) -> str:
        snippet = self.data[:24] + ("…" if len(self.data) > 24 else "")
        return f'QR "{snippet}" · {self.size_mm:g}mm · {self.align}'


@dataclass
class Spacer:
    height_mm: float = 2.0

    def summary(self) -> str:
        return f"Spacer · {self.height_mm:g}mm"


@dataclass
class CutMarker:
    label: str = "cut here"

    def summary(self) -> str:
        return f'Cut mark · "{self.label}"' if self.label else "Cut mark"


Element = Union[TextBlock, QRBlock, Spacer, CutMarker]

ELEMENT_TYPES: dict[str, type] = {
    "text": TextBlock,
    "qr": QRBlock,
    "spacer": Spacer,
    "cut_marker": CutMarker,
}
ELEMENT_TYPE_NAMES: dict[type, str] = {v: k for k, v in ELEMENT_TYPES.items()}


@dataclass
class LabelDoc:
    tape_width_mm: float = 56.0
    usable_width_mm: float = 56.0
    h_align: str = "center"
    sticker_height_mm: float = 0.0      # 0 = continuous tape, no outline drawn
    copies: int = 1
    copy_spacer_mm: float = 3.0
    elements: list = field(default_factory=list)


@dataclass
class Settings:
    printer_name: str = "BTP-L560"
    leading_feed_mm: float = 0.0
    trailing_feed_mm: float = 70.0
    default_font_family: str = "Arial"
    default_size_pt: int = 12


# --------------------------------------------------------------------------- #
# Storage                                                                     #
# --------------------------------------------------------------------------- #

def load_settings() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return Settings()
    fields = Settings.__dataclass_fields__
    return Settings(**{k: v for k, v in data.items() if k in fields})


def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), indent=2))


def doc_to_dict(doc: LabelDoc) -> dict:
    return {
        "schema_version": 1,
        "tape_width_mm": doc.tape_width_mm,
        "usable_width_mm": doc.usable_width_mm,
        "h_align": doc.h_align,
        "sticker_height_mm": doc.sticker_height_mm,
        "copies": doc.copies,
        "copy_spacer_mm": doc.copy_spacer_mm,
        "elements": [
            {"type": ELEMENT_TYPE_NAMES[type(el)], **asdict(el)}
            for el in doc.elements
        ],
    }


def dict_to_doc(data: dict) -> LabelDoc:
    elements: list[Element] = []
    for raw in data.get("elements", []):
        kind = raw.get("type")
        cls = ELEMENT_TYPES.get(kind)
        if cls is None:
            continue
        kwargs = {k: v for k, v in raw.items() if k != "type"}
        try:
            elements.append(cls(**kwargs))
        except TypeError:
            continue
    return LabelDoc(
        tape_width_mm=float(data.get("tape_width_mm", 56.0)),
        usable_width_mm=float(data.get("usable_width_mm", 56.0)),
        h_align=data.get("h_align", "center"),
        sticker_height_mm=float(data.get("sticker_height_mm", 0.0)),
        copies=max(1, int(data.get("copies", 1))),
        copy_spacer_mm=float(data.get("copy_spacer_mm", 3.0)),
        elements=elements,
    )


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
    return cleaned or "untitled"


def save_preset(doc: LabelDoc, name: str) -> Path:
    PRESETS_DIR.mkdir(exist_ok=True)
    path = PRESETS_DIR / f"{_safe_filename(name)}.json"
    path.write_text(json.dumps(doc_to_dict(doc), indent=2))
    return path


def load_preset(path: Path) -> LabelDoc:
    return dict_to_doc(json.loads(path.read_text()))


def list_presets() -> list[Path]:
    if not PRESETS_DIR.exists():
        return []
    return sorted(PRESETS_DIR.glob("*.json"))


# --------------------------------------------------------------------------- #
# Font + render                                                               #
# --------------------------------------------------------------------------- #

def _font_candidates(family: str, bold: bool) -> list[str]:
    fam = (family or "").strip()
    fam_lower = fam.lower()
    fallback = ["arialbd.ttf" if bold else "arial.ttf",
                "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]

    if fam_lower in ("", "arial"):
        if bold:
            return ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]
        return ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    if "dejavu" in fam_lower:
        return ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf"]
    if "comic" in fam_lower:
        if bold:
            return ["comicbd.ttf", "Comic Sans MS Bold.ttf", "comic.ttf"] + fallback
        return ["comic.ttf", "Comic Sans MS.ttf"] + fallback
    if "century" in fam_lower or fam_lower == "gothic":
        if bold:
            return ["GOTHICB.TTF", "gothicb.ttf", "Century Gothic Bold.ttf"] + fallback
        return ["GOTHIC.TTF", "gothic.ttf", "Century Gothic.ttf"] + fallback
    if "old english" in fam_lower or "blackletter" in fam_lower:
        # Old English Text MT has no bold variant — let the regular TTF answer for both.
        return ["OLDENGL.TTF", "oldengl.ttf", "Old English Text MT.ttf"] + fallback
    if "impact" in fam_lower:
        # Impact is already heavy; no separate bold variant on Windows.
        return ["impact.ttf", "Impact.ttf"] + fallback
    if bold:
        return [f"{fam} Bold.ttf", f"{fam}bd.ttf", f"{fam}.ttf"] + fallback
    return [f"{fam}.ttf"] + fallback


def load_font(family: str, size_pt: int, bold: bool) -> ImageFont.ImageFont:
    px = max(1, int(round(size_pt * PT_TO_DOTS)))
    for name in _font_candidates(family, bold):
        try:
            return ImageFont.truetype(name, px)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def _text_width(font: ImageFont.ImageFont, s: str) -> float:
    if hasattr(font, "getlength"):
        return font.getlength(s)
    bbox = font.getbbox(s) if hasattr(font, "getbbox") else (0, 0, 0, 0)
    return bbox[2] - bbox[0]


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    out: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            out.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = word if not current else current + " " + word
            if _text_width(font, trial) <= max_width or not current:
                current = trial
            else:
                out.append(current)
                current = word
        out.append(current)
    return out


def _font_line_height(font: ImageFont.ImageFont) -> int:
    if hasattr(font, "getmetrics"):
        a, d = font.getmetrics()
        return int(a + d)
    if hasattr(font, "getbbox"):
        bbox = font.getbbox("Ag")
        return int(bbox[3] - bbox[1])
    return 12


def render_text(block: TextBlock, width_dots: int, font_family: str) -> Image.Image:
    font = load_font(font_family, block.size_pt, block.bold)
    lines = _wrap_text(block.text, font, width_dots) if block.text else [""]
    line_h = _font_line_height(font)
    height = max(1, line_h * len(lines))

    img = Image.new("L", (width_dots, height), color=255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        line_w = int(_text_width(font, line))
        if block.align == "left":
            x = 0
        elif block.align == "right":
            x = max(0, width_dots - line_w)
        else:
            x = max(0, (width_dots - line_w) // 2)
        draw.text((x, i * line_h), line, fill=0, font=font)
    return img


def render_qr(block: QRBlock, width_dots: int) -> Image.Image:
    if not block.data:
        return Image.new("L", (width_dots, 1), color=255)
    qr = qrcode.QRCode(border=0, box_size=4)
    qr.add_data(block.data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("L")
    target = max(1, int(round(block.size_mm * DOTS_PER_MM)))
    target = min(target, width_dots)
    qr_img = qr_img.resize((target, target), Image.Resampling.NEAREST)

    canvas = Image.new("L", (width_dots, target), color=255)
    if block.align == "left":
        x = 0
    elif block.align == "right":
        x = width_dots - target
    else:
        x = (width_dots - target) // 2
    canvas.paste(qr_img, (x, 0))
    return canvas


def render_spacer(block: Spacer, width_dots: int) -> Image.Image:
    h = max(1, int(round(block.height_mm * DOTS_PER_MM)))
    return Image.new("L", (width_dots, h), color=255)


def _draw_dashed_hline(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int,
                       fill, width: int = 2, seg: int = 8, gap: int = 5) -> None:
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + seg, x1), y)], fill=fill, width=width)
        x += seg + gap


def _draw_dashed_vline(draw: ImageDraw.ImageDraw, y0: int, y1: int, x: int,
                       fill, width: int = 2, seg: int = 8, gap: int = 5) -> None:
    y = y0
    while y < y1:
        draw.line([(x, y), (x, min(y + seg, y1))], fill=fill, width=width)
        y += seg + gap


def _draw_dashed_rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
                      fill, width: int = 2) -> None:
    x0, y0, x1, y1 = box
    _draw_dashed_hline(draw, x0, x1, y0, fill, width)
    _draw_dashed_hline(draw, x0, x1, y1 - 1, fill, width)
    _draw_dashed_vline(draw, y0, y1, x0, fill, width)
    _draw_dashed_vline(draw, y0, y1, x1 - 1, fill, width)


def render_cut_marker(block: CutMarker, width_dots: int, font_family: str) -> Image.Image:
    cap_font = load_font(font_family, 7, False) if block.label else None
    cap_h = _font_line_height(cap_font) if cap_font else 0
    dash_band = max(2, int(round(1.5 * DOTS_PER_MM)))
    total = cap_h + dash_band

    img = Image.new("L", (width_dots, total), color=255)
    draw = ImageDraw.Draw(img)
    if cap_font and block.label:
        cap_w = int(_text_width(cap_font, block.label))
        x = max(0, (width_dots - cap_w) // 2)
        draw.text((x, 0), block.label, fill=0, font=cap_font)

    y = cap_h + dash_band // 2
    _draw_dashed_hline(draw, 0, width_dots, y, fill=0, width=2)
    return img


def _render_single_copy(doc: LabelDoc, font_family: str) -> Image.Image:
    """Render exactly one copy of the document — no copies/spacers applied."""
    tape_dots = min(MAX_PRINT_WIDTH_DOTS, max(1, int(round(doc.tape_width_mm * DOTS_PER_MM))))
    usable_dots = min(MAX_PRINT_WIDTH_DOTS, max(1, int(round(doc.usable_width_mm * DOTS_PER_MM))))
    usable_dots = min(usable_dots, tape_dots)

    strips: list[Image.Image] = []
    for el in doc.elements:
        if isinstance(el, TextBlock):
            strips.append(render_text(el, usable_dots, font_family))
        elif isinstance(el, QRBlock):
            strips.append(render_qr(el, usable_dots))
        elif isinstance(el, Spacer):
            strips.append(render_spacer(el, usable_dots))
        elif isinstance(el, CutMarker):
            strips.append(render_cut_marker(el, usable_dots, font_family))

    if not strips:
        blank_h = max(1, int(round(20 * DOTS_PER_MM)))
        return Image.new("L", (tape_dots, blank_h), color=255)

    total_h = sum(s.height for s in strips)
    usable_canvas = Image.new("L", (usable_dots, total_h), color=255)
    y = 0
    for strip in strips:
        usable_canvas.paste(strip, (0, y))
        y += strip.height

    if usable_dots == tape_dots:
        return usable_canvas

    full = Image.new("L", (tape_dots, total_h), color=255)
    if doc.h_align == "left":
        x = 0
    elif doc.h_align == "right":
        x = tape_dots - usable_dots
    else:
        x = (tape_dots - usable_dots) // 2
    full.paste(usable_canvas, (x, 0))
    return full


def _slot_geometry(doc: LabelDoc, content_h: int) -> tuple[int, int, int]:
    """Return (slot_height_dots, spacer_dots, copies) for the multi-copy stack.

    slot_height = max(content_h, sticker_height_dots) so a content-taller-than
    -sticker case overflows downward but doesn't break.
    """
    copies = max(1, min(200, doc.copies))
    sticker_dots = max(0, int(round(doc.sticker_height_mm * DOTS_PER_MM)))
    slot_h = max(content_h, sticker_dots) if sticker_dots > 0 else content_h
    spacer_dots = max(0, int(round(doc.copy_spacer_mm * DOTS_PER_MM))) if copies > 1 else 0
    return slot_h, spacer_dots, copies


def render_label(doc: LabelDoc, font_family: str) -> Image.Image:
    """Bitmap that gets sent to the printer — N copies stacked with spacers."""
    single = _render_single_copy(doc, font_family)
    slot_h, spacer_dots, copies = _slot_geometry(doc, single.height)

    if copies == 1 and slot_h == single.height:
        return single

    total_h = copies * slot_h + (copies - 1) * spacer_dots
    canvas = Image.new("L", (single.width, total_h), color=255)
    for i in range(copies):
        slot_top = i * (slot_h + spacer_dots)
        canvas.paste(single, (0, slot_top))
    return canvas


def render_preview(doc: LabelDoc, font_family: str) -> Image.Image:
    """Preview render — same bitmap as render_label() plus red dashed sticker outlines.

    The outline never reaches the printer; print_doc() calls render_label().
    """
    bitmap = render_label(doc, font_family)
    if doc.sticker_height_mm <= 0:
        return bitmap.convert("RGB")

    rgb = bitmap.convert("RGB")
    draw = ImageDraw.Draw(rgb)
    single_h = _render_single_copy(doc, font_family).height
    slot_h, spacer_dots, copies = _slot_geometry(doc, single_h)
    sticker_dots = max(1, int(round(doc.sticker_height_mm * DOTS_PER_MM)))
    usable_dots = min(MAX_PRINT_WIDTH_DOTS, max(1, int(round(doc.usable_width_mm * DOTS_PER_MM))))
    tape_dots = min(MAX_PRINT_WIDTH_DOTS, max(1, int(round(doc.tape_width_mm * DOTS_PER_MM))))
    usable_dots = min(usable_dots, tape_dots)
    if doc.h_align == "left":
        outline_x0 = 0
    elif doc.h_align == "right":
        outline_x0 = tape_dots - usable_dots
    else:
        outline_x0 = (tape_dots - usable_dots) // 2
    outline_x1 = outline_x0 + usable_dots

    red = (220, 30, 30)
    for i in range(copies):
        slot_top = i * (slot_h + spacer_dots)
        _draw_dashed_rect(draw, (outline_x0, slot_top, outline_x1, slot_top + sticker_dots),
                          fill=red, width=2)
    return rgb


# --------------------------------------------------------------------------- #
# Print                                                                       #
# --------------------------------------------------------------------------- #

def _feed_mm(p, mm: float) -> None:
    """Feed paper N millimetres using ESC J (chunked at 255 dots / call)."""
    dots = int(mm * DOTS_PER_MM)
    while dots > 0:
        chunk = min(dots, 255)
        p._raw(b"\x1bJ" + bytes([chunk]))
        dots -= chunk


def print_doc(doc: LabelDoc, settings: Settings) -> None:
    if Win32Raw is None:
        raise RuntimeError(
            "python-escpos Win32Raw is not available. Install python-escpos and run on Windows."
        )
    img = render_label(doc, settings.default_font_family)
    # Threshold without dithering — sharper text on thermal media.
    bw = img.convert("1", dither=Image.Dither.NONE)

    p = Win32Raw(printer_name=settings.printer_name)
    try:
        if settings.leading_feed_mm > 0:
            _feed_mm(p, settings.leading_feed_mm)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            p.image(bw, impl="bitImageColumn")
        if settings.trailing_feed_mm > 0:
            _feed_mm(p, settings.trailing_feed_mm)
    finally:
        p.close()


# --------------------------------------------------------------------------- #
# GUI                                                                         #
# --------------------------------------------------------------------------- #

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, settings: Settings, on_save: Callable[[Settings], None]) -> None:
        super().__init__(parent)
        self.title("Settings")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self._on_save = on_save

        self.printer_var = tk.StringVar(value=settings.printer_name)
        self.lead_var = tk.DoubleVar(value=settings.leading_feed_mm)
        self.trail_var = tk.DoubleVar(value=settings.trailing_feed_mm)
        self.font_var = tk.StringVar(value=settings.default_font_family)
        self.size_var = tk.IntVar(value=settings.default_size_pt)

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Printer name:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(body, textvariable=self.printer_var, width=24).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(body, text="Leading feed (mm):").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Spinbox(body, from_=0, to=200, increment=1, textvariable=self.lead_var, width=10).grid(
            row=1, column=1, sticky="w", pady=4)

        ttk.Label(body, text="Trailing feed (mm):").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        ttk.Spinbox(body, from_=0, to=200, increment=1, textvariable=self.trail_var, width=10).grid(
            row=2, column=1, sticky="w", pady=4)

        ttk.Label(body, text="Default font:").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        # Preserve a custom legacy value (from a hand-edited settings file) by prepending it.
        font_values = list(FONT_FAMILIES)
        current_font = self.font_var.get().strip()
        if current_font and current_font not in font_values:
            font_values.insert(0, current_font)
        ttk.Combobox(body, textvariable=self.font_var, values=font_values,
                     state="readonly", width=22).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(body, text="Default text size (pt):").grid(row=4, column=0, sticky="w", padx=4, pady=4)
        ttk.Spinbox(body, from_=6, to=96, increment=1, textvariable=self.size_var, width=10).grid(
            row=4, column=1, sticky="w", pady=4)

        body.columnconfigure(1, weight=1)

        btns = ttk.Frame(self, padding=(12, 0, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="right")

    def _save(self) -> None:
        try:
            new = Settings(
                printer_name=self.printer_var.get().strip() or "BTP-L560",
                leading_feed_mm=float(self.lead_var.get()),
                trailing_feed_mm=float(self.trail_var.get()),
                default_font_family=self.font_var.get().strip() or "Arial",
                default_size_pt=max(6, int(self.size_var.get())),
            )
        except (ValueError, TypeError) as e:
            messagebox.showerror("Invalid settings", str(e), parent=self)
            return
        self._on_save(new)
        self.destroy()


class LabelApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Flex Label — BTP-L560")
        self.geometry("1100x720")
        self.minsize(960, 620)

        self.settings = load_settings()
        self.doc = LabelDoc()
        self.selected_index: int | None = None
        self._preview_image_ref: ImageTk.PhotoImage | None = None

        self._build_menu()
        self._build_layout()
        self.refresh_all()

    # ---- Menu ----
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="New", command=self.action_new)
        filemenu.add_command(label="Save Preset…", command=self.action_save_preset)
        filemenu.add_command(label="Load Preset…", command=self.action_load_preset_dialog)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Open Settings…", command=self.action_open_settings)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._help_about)
        help_menu.add_separator()
        help_menu.add_command(label="Tape & sticker sizes…", command=self._help_tape)
        help_menu.add_command(label="Element types…", command=self._help_elements)
        help_menu.add_command(label="Printing & feed tuning…", command=self._help_printing)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _help_window(self, title: str, body: str) -> None:
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        text = tk.Text(win, wrap="word", width=72, height=24,
                       padx=12, pady=10, relief="flat", background="#fafafa")
        text.insert("1.0", body)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)

    def _help_about(self) -> None:
        self._help_window(
            "About Flex Label",
            "Flex Label — block-based designer for the Alere BTP-L560.\n"
            "\n"
            "Talks ESC/POS over the Windows print spooler (python-escpos\n"
            "Win32Raw). Should work on most other ESC/POS thermal label or\n"
            "receipt printers — anything that accepts raw ESC/POS bytes and\n"
            "renders bitmaps via GS v 0 / ESC * — though tear-bar feed and\n"
            "media width may need tuning in Settings.\n"
            "\n"
            "Per-block formatting · QR · spacers · cut markers · live preview.\n\n"
            "Presets are stored as JSON files in ./presets/ next to the script.\n"
            "Settings are stored in flex_label_settings.json.\n\n"
            "Run on Windows to print. The GUI and preview also work on Linux/WSL "
            "but the Print button needs the Windows print spooler.",
        )

    def _help_tape(self) -> None:
        self._help_window(
            "Tape & sticker sizes",
            "TAPE WIDTH is the physical width of the paper coming out of the\n"
            "printer — not the printable area, not the sticker face. For OEM\n"
            "Alere rolls that's 56 mm. For 58 mm continuous receipt rolls it's\n"
            "58 mm. Set this to whatever roll you have loaded.\n"
            "\n"
            "USABLE WIDTH is how much of that tape you actually want to print on.\n"
            "Set it smaller than the tape width if your stickers have a margin\n"
            "or you only want a strip of content. \"Place usable area\" controls\n"
            "whether the unused band sits on the left, right, or splits centred.\n"
            "\n"
            "STICKER HEIGHT is the height of one die-cut sticker (e.g. 70 mm for\n"
            "the OEM Alere rolls, 40 mm for many generic 60×40 rolls). When set,\n"
            "the preview draws a red dashed rectangle around each sticker so you\n"
            "can see how your content fits — handy for checking that a \"big\"\n"
            "layout actually fits, or that smaller content sits where you want\n"
            "it inside the sticker. Set to 0 for continuous tape (no outline).\n"
            "\n"
            "MULTI-COPY PRINTING. The Copies field stacks N duplicates of your\n"
            "design in one print job, separated by the configurable mm gap.\n"
            "Use \"Fill to: [N] mm  [Calc copies]\" to compute how many copies\n"
            "fit in a target tape length — type the target, click Calc, the\n"
            "Copies field updates. Then Print and scissor them apart.\n"
            "\n"
            "TRAILING FEED in Settings (default 70 mm) is the separate \"advance\n"
            "the tape so the perforation clears the tear bar\" knob — not the\n"
            "same as sticker height. If your tear is short, raise it; if you\n"
            "waste a blank label between prints, lower it.",
        )

    def _help_elements(self) -> None:
        self._help_window(
            "Element types",
            "TEXT BLOCK\n"
            "  A paragraph with its own font size (in points), bold flag, and\n"
            "  alignment. Add more than one to mix sizes — e.g. a big bold\n"
            "  \"title\" block above a smaller body block.\n"
            "\n"
            "QR CODE\n"
            "  Encodes any string (URL, lot number, free text). Size in mm.\n"
            "  Scans cleanly down to about 12 mm at this resolution.\n"
            "\n"
            "SPACER\n"
            "  Blank vertical space, in millimetres. Has NO visible content —\n"
            "  it just pushes the next block down. Use it for breathing room\n"
            "  between two text blocks.\n"
            "\n"
            "CUT MARKER\n"
            "  A dashed line with an optional caption like \"cut here\". DOES\n"
            "  print — it's a visible mark on the tape so you know where to\n"
            "  scissor. Use this between two stickers' worth of content when\n"
            "  printing several labels on one stretch of tape.\n"
            "\n"
            "Spacer vs Cut marker: a Spacer is invisible whitespace; a Cut\n"
            "Marker is a printed line that tells you where to scissor.\n"
            "\n"
            "Re-order blocks with the ↑ Up / ↓ Down buttons. Delete with ✕.",
        )

    def _help_printing(self) -> None:
        self._help_window(
            "Printing & feed tuning",
            "PRINTER NAME\n"
            "  Windows printer queue name. Default \"BTP-L560\" (matches the\n"
            "  install in RECIPE.md). If you renamed the queue, run\n"
            "  `python list_printers.py` to find the exact name and paste it\n"
            "  here.\n"
            "\n"
            "LEADING FEED (mm)\n"
            "  Paper advanced BEFORE printing. Set this small positive value\n"
            "  if your content lands too high on the sticker. Typical: 0.\n"
            "\n"
            "TRAILING FEED (mm)\n"
            "  Paper advanced AFTER printing. Default 70 mm. This pushes the\n"
            "  printed sticker past the tear bar so you can rip it off cleanly.\n"
            "  Raise it if your tear edge is short of the bar; lower it if you\n"
            "  waste a blank label between prints.\n"
            "\n"
            "DEFAULT FONT / DEFAULT SIZE (pt)\n"
            "  Applied to NEW text blocks you add from now on. Existing blocks\n"
            "  keep their own size. The dropdown lists fonts that ship with\n"
            "  Windows or MS Office; if a font isn't installed, the app silently\n"
            "  falls back to Arial.",
        )

    # ---- Layout ----
    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=0, minsize=240)
        self.columnconfigure(1, weight=1, minsize=380)
        self.columnconfigure(2, weight=1, minsize=320)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=8)
        mid = ttk.Frame(self, padding=8)
        right = ttk.Frame(self, padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        mid.grid(row=0, column=1, sticky="nsew")
        right.grid(row=0, column=2, sticky="nsew")

        self._build_left(left)
        self._build_mid(mid)
        self._build_right(right)

    def _build_left(self, parent: ttk.Frame) -> None:
        tape = ttk.LabelFrame(parent, text="Tape", padding=8)
        tape.pack(fill="x", pady=(0, 8))

        self.tape_width_var = tk.DoubleVar(value=self.doc.tape_width_mm)
        self.usable_width_var = tk.DoubleVar(value=self.doc.usable_width_mm)
        self.h_align_var = tk.StringVar(value=self.doc.h_align)

        ttk.Label(tape, text="Tape width (mm):").grid(row=0, column=0, sticky="w", pady=2)
        tw = ttk.Spinbox(tape, from_=10, to=80, increment=1,
                         textvariable=self.tape_width_var, width=8,
                         command=self._on_tape_change)
        tw.grid(row=0, column=1, sticky="ew", pady=2)
        tw.bind("<KeyRelease>", lambda e: self._on_tape_change())

        ttk.Label(tape, text="Usable width (mm):").grid(row=1, column=0, sticky="w", pady=2)
        uw = ttk.Spinbox(tape, from_=10, to=80, increment=1,
                         textvariable=self.usable_width_var, width=8,
                         command=self._on_tape_change)
        uw.grid(row=1, column=1, sticky="ew", pady=2)
        uw.bind("<KeyRelease>", lambda e: self._on_tape_change())

        ttk.Label(tape, text="Place usable area:").grid(row=2, column=0, sticky="w", pady=(8, 2))
        align_row = ttk.Frame(tape)
        align_row.grid(row=2, column=1, sticky="w")
        for opt in ALIGN_OPTIONS:
            ttk.Radiobutton(align_row, text=opt.capitalize(), value=opt,
                            variable=self.h_align_var,
                            command=self._on_tape_change).pack(side="left")

        self.sticker_height_var = tk.DoubleVar(value=self.doc.sticker_height_mm)
        ttk.Label(tape, text="Sticker height (mm):").grid(row=3, column=0, sticky="w", pady=(8, 2))
        sh = ttk.Spinbox(tape, from_=0, to=200, increment=1,
                         textvariable=self.sticker_height_var, width=8,
                         command=self._on_tape_change)
        sh.grid(row=3, column=1, sticky="w", pady=(8, 2))
        sh.bind("<KeyRelease>", lambda e: self._on_tape_change())
        ttk.Label(tape, text="0 = continuous (no outline)",
                  foreground="#888").grid(row=4, column=0, columnspan=2, sticky="w")

        tape.columnconfigure(1, weight=1)

        copies_frame = ttk.LabelFrame(parent, text="Copies", padding=8)
        copies_frame.pack(fill="x", pady=(0, 8))

        self.copies_var = tk.IntVar(value=self.doc.copies)
        self.copy_spacer_var = tk.DoubleVar(value=self.doc.copy_spacer_mm)
        self.fill_target_var = tk.DoubleVar(value=200.0)

        ttk.Label(copies_frame, text="Count:").grid(row=0, column=0, sticky="w", pady=2)
        cn = ttk.Spinbox(copies_frame, from_=1, to=200, increment=1,
                         textvariable=self.copies_var, width=8,
                         command=self._on_copies_change)
        cn.grid(row=0, column=1, sticky="w", pady=2)
        cn.bind("<KeyRelease>", lambda e: self._on_copies_change())

        ttk.Label(copies_frame, text="Gap between (mm):").grid(row=1, column=0, sticky="w", pady=2)
        gp = ttk.Spinbox(copies_frame, from_=0, to=50, increment=0.5,
                         textvariable=self.copy_spacer_var, width=8,
                         command=self._on_copies_change)
        gp.grid(row=1, column=1, sticky="w", pady=2)
        gp.bind("<KeyRelease>", lambda e: self._on_copies_change())

        fill_row = ttk.Frame(copies_frame)
        fill_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(fill_row, text="Fill to:").pack(side="left")
        ttk.Spinbox(fill_row, from_=10, to=2000, increment=10,
                    textvariable=self.fill_target_var, width=7).pack(side="left", padx=(2, 2))
        ttk.Label(fill_row, text="mm").pack(side="left")
        ttk.Button(fill_row, text="Calc copies",
                   command=self.action_calc_copies).pack(side="right")

        copies_frame.columnconfigure(1, weight=1)

        preset = ttk.LabelFrame(parent, text="Presets", padding=8)
        preset.pack(fill="x", pady=(0, 8))
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset, textvariable=self.preset_var, state="readonly")
        self.preset_combo.pack(fill="x", pady=2)
        # No auto-load on dropdown selection — Load is an explicit click below.

        btnrow = ttk.Frame(preset)
        btnrow.pack(fill="x", pady=2)
        ttk.Button(btnrow, text="Save", command=self.action_save_preset).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        ttk.Button(btnrow, text="Load", command=self.action_load_selected_preset).pack(
            side="left", expand=True, fill="x", padx=2)
        ttk.Button(btnrow, text="Delete", command=self.action_delete_preset).pack(
            side="left", expand=True, fill="x", padx=(2, 0))

        self.print_btn = ttk.Button(parent, text="Print", command=self.action_print)
        self.print_btn.pack(fill="x", pady=8)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(parent, textvariable=self.status_var, foreground="#666",
                  wraplength=220, justify="left").pack(fill="x")

    def _build_mid(self, parent: ttk.Frame) -> None:
        add = ttk.Frame(parent)
        add.pack(fill="x")
        ttk.Button(add, text="+ Text",
                   command=lambda: self.action_add(TextBlock(size_pt=self.settings.default_size_pt))
                   ).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(add, text="+ QR",
                   command=lambda: self.action_add(QRBlock())
                   ).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(add, text="+ Spacer",
                   command=lambda: self.action_add(Spacer())
                   ).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(add, text="+ Cut",
                   command=lambda: self.action_add(CutMarker())
                   ).pack(side="left", expand=True, fill="x", padx=2)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", pady=(8, 4))
        self.tree = ttk.Treeview(tree_frame, columns=("summary",), show="headings", height=8)
        self.tree.heading("summary", text="Element")
        self.tree.column("summary", width=360)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(tree_frame, command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        ctrl = ttk.Frame(parent)
        ctrl.pack(fill="x")
        ttk.Button(ctrl, text="↑ Up", command=self.action_move_up).pack(
            side="left", expand=True, fill="x", padx=2)
        ttk.Button(ctrl, text="↓ Down", command=self.action_move_down).pack(
            side="left", expand=True, fill="x", padx=2)
        ttk.Button(ctrl, text="✕ Delete", command=self.action_delete).pack(
            side="left", expand=True, fill="x", padx=2)

        self.editor_frame = ttk.LabelFrame(parent, text="Edit element", padding=8)
        self.editor_frame.pack(fill="both", expand=True, pady=(8, 0))
        self._build_empty_editor()

    def _build_right(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text=f"Preview ({PREVIEW_ZOOM}× zoom)").pack(anchor="w")
        canvas_frame = ttk.Frame(parent, relief="sunken", borderwidth=1)
        canvas_frame.pack(fill="both", expand=True, pady=4)
        self.preview_canvas = tk.Canvas(canvas_frame, bg="#dddddd", highlightthickness=0)
        v = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.preview_canvas.yview)
        self.preview_canvas.configure(yscrollcommand=v.set)
        v.pack(side="right", fill="y")
        self.preview_canvas.pack(side="left", fill="both", expand=True)

        self.preview_info_var = tk.StringVar(value="—")
        ttk.Label(parent, textvariable=self.preview_info_var, foreground="#666").pack(anchor="w")

    # ---- Editor frames ----
    def _clear_editor(self) -> None:
        for w in self.editor_frame.winfo_children():
            w.destroy()

    def _build_empty_editor(self) -> None:
        self._clear_editor()
        ttk.Label(self.editor_frame,
                  text="Select or add an element to edit it.",
                  foreground="#666").pack(pady=20)

    def _build_text_editor(self, idx: int, block: TextBlock) -> None:
        self._clear_editor()
        ttk.Label(self.editor_frame, text="Text:").grid(row=0, column=0, sticky="nw", pady=2)
        text_widget = tk.Text(self.editor_frame, height=4, wrap="word", width=40)
        text_widget.insert("1.0", block.text)
        text_widget.grid(row=0, column=1, columnspan=3, sticky="nsew", pady=2)
        text_widget.edit_modified(False)
        text_widget.bind("<<Modified>>",
                         lambda e: self._on_text_changed(idx, text_widget))

        ttk.Label(self.editor_frame, text="Size (pt):").grid(row=1, column=0, sticky="w", pady=4)
        size_var = tk.IntVar(value=block.size_pt)
        size_spin = ttk.Spinbox(self.editor_frame, from_=6, to=96, increment=1,
                                textvariable=size_var, width=6,
                                command=lambda: self._safe_set(idx, "size_pt", lambda: int(size_var.get())))
        size_spin.grid(row=1, column=1, sticky="w", pady=4)
        size_spin.bind("<KeyRelease>",
                       lambda e: self._safe_set(idx, "size_pt", lambda: int(size_var.get())))

        bold_var = tk.BooleanVar(value=block.bold)
        ttk.Checkbutton(self.editor_frame, text="Bold", variable=bold_var,
                        command=lambda: self._set_field(idx, "bold", bold_var.get())
                        ).grid(row=1, column=2, sticky="w", padx=8)

        align_row = ttk.Frame(self.editor_frame)
        align_row.grid(row=2, column=0, columnspan=4, sticky="w", pady=4)
        ttk.Label(align_row, text="Align:").pack(side="left", padx=(0, 4))
        align_var = tk.StringVar(value=block.align)
        for opt in ALIGN_OPTIONS:
            ttk.Radiobutton(align_row, text=opt.capitalize(), value=opt, variable=align_var,
                            command=lambda v=align_var: self._set_field(idx, "align", v.get())
                            ).pack(side="left")

        self.editor_frame.columnconfigure(1, weight=1)
        self.editor_frame.rowconfigure(0, weight=1)

    def _on_text_changed(self, idx: int, widget: tk.Text) -> None:
        if not widget.edit_modified():
            return
        new_text = widget.get("1.0", "end-1c")
        self._set_field(idx, "text", new_text)
        widget.edit_modified(False)

    def _build_qr_editor(self, idx: int, block: QRBlock) -> None:
        self._clear_editor()
        ttk.Label(self.editor_frame, text="Data / URL:").grid(row=0, column=0, sticky="w", pady=2)
        data_var = tk.StringVar(value=block.data)
        data_entry = ttk.Entry(self.editor_frame, textvariable=data_var)
        data_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        data_entry.bind("<KeyRelease>",
                        lambda e: self._set_field(idx, "data", data_var.get()))

        ttk.Label(self.editor_frame, text="Size (mm):").grid(row=1, column=0, sticky="w", pady=4)
        size_var = tk.DoubleVar(value=block.size_mm)
        size_spin = ttk.Spinbox(self.editor_frame, from_=5, to=56, increment=1,
                                textvariable=size_var, width=6,
                                command=lambda: self._safe_set(idx, "size_mm", lambda: float(size_var.get())))
        size_spin.grid(row=1, column=1, sticky="w", pady=4)
        size_spin.bind("<KeyRelease>",
                       lambda e: self._safe_set(idx, "size_mm", lambda: float(size_var.get())))

        align_row = ttk.Frame(self.editor_frame)
        align_row.grid(row=2, column=0, columnspan=4, sticky="w", pady=4)
        ttk.Label(align_row, text="Align:").pack(side="left", padx=(0, 4))
        align_var = tk.StringVar(value=block.align)
        for opt in ALIGN_OPTIONS:
            ttk.Radiobutton(align_row, text=opt.capitalize(), value=opt, variable=align_var,
                            command=lambda v=align_var: self._set_field(idx, "align", v.get())
                            ).pack(side="left")

        self.editor_frame.columnconfigure(1, weight=1)

    def _build_spacer_editor(self, idx: int, block: Spacer) -> None:
        self._clear_editor()
        ttk.Label(self.editor_frame, text="Height (mm):").grid(row=0, column=0, sticky="w", pady=4)
        h_var = tk.DoubleVar(value=block.height_mm)
        h_spin = ttk.Spinbox(self.editor_frame, from_=0.5, to=80, increment=0.5,
                             textvariable=h_var, width=8,
                             command=lambda: self._safe_set(idx, "height_mm", lambda: float(h_var.get())))
        h_spin.grid(row=0, column=1, sticky="w", pady=4)
        h_spin.bind("<KeyRelease>",
                    lambda e: self._safe_set(idx, "height_mm", lambda: float(h_var.get())))

    def _build_cut_marker_editor(self, idx: int, block: CutMarker) -> None:
        self._clear_editor()
        ttk.Label(self.editor_frame, text="Caption (optional):").grid(row=0, column=0, sticky="w", pady=4)
        cap_var = tk.StringVar(value=block.label)
        cap_entry = ttk.Entry(self.editor_frame, textvariable=cap_var)
        cap_entry.grid(row=0, column=1, sticky="ew", pady=4)
        cap_entry.bind("<KeyRelease>",
                       lambda e: self._set_field(idx, "label", cap_var.get()))
        self.editor_frame.columnconfigure(1, weight=1)

    # ---- Model setters ----
    def _set_field(self, idx: int | None, field_name: str, value: object) -> None:
        if idx is None or idx < 0 or idx >= len(self.doc.elements):
            return
        setattr(self.doc.elements[idx], field_name, value)
        self.refresh_tree_row(idx)
        self.refresh_preview()

    def _safe_set(self, idx: int | None, field_name: str, getter: Callable[[], object]) -> None:
        try:
            value = getter()
        except (ValueError, TypeError, tk.TclError):
            return
        self._set_field(idx, field_name, value)

    def _on_tape_change(self) -> None:
        try:
            self.doc.tape_width_mm = float(self.tape_width_var.get())
            self.doc.usable_width_mm = float(self.usable_width_var.get())
            self.doc.sticker_height_mm = max(0.0, float(self.sticker_height_var.get()))
        except (ValueError, TypeError, tk.TclError):
            return
        self.doc.h_align = self.h_align_var.get()
        self.refresh_preview()

    def _on_copies_change(self) -> None:
        try:
            self.doc.copies = max(1, min(200, int(self.copies_var.get())))
            self.doc.copy_spacer_mm = max(0.0, float(self.copy_spacer_var.get()))
        except (ValueError, TypeError, tk.TclError):
            return
        self.refresh_preview()

    def action_calc_copies(self) -> None:
        try:
            target_mm = float(self.fill_target_var.get())
        except (ValueError, TypeError, tk.TclError):
            messagebox.showerror("Calc copies", "Enter a target length in mm.")
            return
        single = _render_single_copy(self.doc, self.settings.default_font_family)
        h_single_mm = single.height / DOTS_PER_MM
        slot_mm = max(h_single_mm, self.doc.sticker_height_mm) if self.doc.sticker_height_mm > 0 else h_single_mm
        spacer = max(0.0, self.doc.copy_spacer_mm)
        if slot_mm <= 0:
            return
        # k slots take k*slot + (k-1)*spacer ≤ target
        k = int((target_mm + spacer) // (slot_mm + spacer))
        if k < 1:
            messagebox.showinfo(
                "Calc copies",
                f"One copy is {slot_mm:.1f} mm — doesn't fit in {target_mm:.0f} mm.",
            )
            return
        self.copies_var.set(k)
        self._on_copies_change()
        self.status_var.set(f"Set copies to {k} (fits {target_mm:.0f} mm).")

    # ---- Selection / list actions ----
    def _on_select(self, _event: object = None) -> None:
        sel = self.tree.selection()
        if not sel:
            self.selected_index = None
            self._build_empty_editor()
            return
        idx = self.tree.index(sel[0])
        self.selected_index = idx
        block = self.doc.elements[idx]
        if isinstance(block, TextBlock):
            self._build_text_editor(idx, block)
        elif isinstance(block, QRBlock):
            self._build_qr_editor(idx, block)
        elif isinstance(block, Spacer):
            self._build_spacer_editor(idx, block)
        elif isinstance(block, CutMarker):
            self._build_cut_marker_editor(idx, block)

    def action_add(self, element: Element) -> None:
        self.doc.elements.append(element)
        self.refresh_tree()
        self._select_index(len(self.doc.elements) - 1)
        self.refresh_preview()

    def action_delete(self) -> None:
        if self.selected_index is None:
            return
        del self.doc.elements[self.selected_index]
        self.selected_index = None
        self.refresh_tree()
        self._build_empty_editor()
        self.refresh_preview()

    def action_move_up(self) -> None:
        i = self.selected_index
        if i is None or i <= 0:
            return
        self.doc.elements[i - 1], self.doc.elements[i] = self.doc.elements[i], self.doc.elements[i - 1]
        self.refresh_tree()
        self._select_index(i - 1)
        self.refresh_preview()

    def action_move_down(self) -> None:
        i = self.selected_index
        if i is None or i >= len(self.doc.elements) - 1:
            return
        self.doc.elements[i + 1], self.doc.elements[i] = self.doc.elements[i], self.doc.elements[i + 1]
        self.refresh_tree()
        self._select_index(i + 1)
        self.refresh_preview()

    # ---- File / preset / settings actions ----
    def action_new(self) -> None:
        if self.doc.elements and not messagebox.askyesno(
            "New Label", "Discard current label and start fresh?"
        ):
            return
        self.doc = LabelDoc()
        self.tape_width_var.set(self.doc.tape_width_mm)
        self.usable_width_var.set(self.doc.usable_width_mm)
        self.h_align_var.set(self.doc.h_align)
        self.sticker_height_var.set(self.doc.sticker_height_mm)
        self.copies_var.set(self.doc.copies)
        self.copy_spacer_var.set(self.doc.copy_spacer_mm)
        self.preset_var.set("")
        self.selected_index = None
        self.refresh_all()
        self.status_var.set("New label.")

    def action_save_preset(self) -> None:
        suggested = self.preset_var.get() or ""
        name = simpledialog.askstring("Save Preset", "Preset name:", initialvalue=suggested, parent=self)
        if not name:
            return
        path = save_preset(self.doc, name)
        self._refresh_preset_combo()
        self.preset_var.set(path.stem)
        self.status_var.set(f"Saved {path.name}.")

    def action_load_preset_dialog(self) -> None:
        PRESETS_DIR.mkdir(exist_ok=True)
        path_str = filedialog.askopenfilename(
            initialdir=str(PRESETS_DIR),
            filetypes=[("Flex Label preset", "*.json")],
        )
        if not path_str:
            return
        self._load_preset_path(Path(path_str))

    def action_load_selected_preset(self) -> None:
        # Pick up new files dropped into ./presets/ since the app started.
        self._refresh_preset_combo()
        name = self.preset_var.get()
        if not name:
            messagebox.showinfo("Load preset", "Pick a preset from the dropdown first.")
            return
        path = PRESETS_DIR / f"{name}.json"
        if not path.exists():
            messagebox.showerror("Load failed", f"{path.name} not found.")
            return
        self._load_preset_path(path)

    def _load_preset_path(self, path: Path) -> None:
        try:
            self.doc = load_preset(path)
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("Load failed", str(e))
            return
        self.tape_width_var.set(self.doc.tape_width_mm)
        self.usable_width_var.set(self.doc.usable_width_mm)
        self.h_align_var.set(self.doc.h_align)
        self.sticker_height_var.set(self.doc.sticker_height_mm)
        self.copies_var.set(self.doc.copies)
        self.copy_spacer_var.set(self.doc.copy_spacer_mm)
        self.selected_index = None
        self.refresh_all()
        self.status_var.set(f"Loaded {path.name}.")

    def action_delete_preset(self) -> None:
        name = self.preset_var.get()
        if not name:
            return
        path = PRESETS_DIR / f"{name}.json"
        if not path.exists():
            return
        if not messagebox.askyesno("Delete preset", f"Delete {path.name}?"):
            return
        path.unlink()
        self._refresh_preset_combo()
        self.preset_var.set("")
        self.status_var.set(f"Deleted {path.name}.")

    def _refresh_preset_combo(self) -> None:
        self.preset_combo["values"] = [p.stem for p in list_presets()]

    def action_open_settings(self) -> None:
        SettingsDialog(self, self.settings, on_save=self._settings_saved)

    def _settings_saved(self, new_settings: Settings) -> None:
        self.settings = new_settings
        save_settings(new_settings)
        self.status_var.set("Settings saved.")
        self.refresh_preview()

    def action_print(self) -> None:
        if not self.doc.elements:
            messagebox.showwarning("Nothing to print", "Add at least one element first.")
            return
        try:
            print_doc(self.doc, self.settings)
            self.status_var.set("Printed.")
        except Exception as e:  # noqa: BLE001 — surface any print error to the user
            messagebox.showerror("Print failed", str(e))
            self.status_var.set("Print failed.")

    # ---- Refresh ----
    def refresh_all(self) -> None:
        self.refresh_tree()
        self._refresh_preset_combo()
        self.refresh_preview()
        self._build_empty_editor()

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for el in self.doc.elements:
            self.tree.insert("", "end", values=(el.summary(),))

    def refresh_tree_row(self, idx: int) -> None:
        children = self.tree.get_children()
        if 0 <= idx < len(children):
            self.tree.item(children[idx], values=(self.doc.elements[idx].summary(),))

    def _select_index(self, idx: int) -> None:
        children = self.tree.get_children()
        if 0 <= idx < len(children):
            self.tree.selection_set(children[idx])
            self.tree.focus(children[idx])

    def refresh_preview(self) -> None:
        try:
            img = render_preview(self.doc, self.settings.default_font_family)
        except Exception as e:  # noqa: BLE001 — render bugs shouldn't crash the GUI
            self.status_var.set(f"Preview error: {e}")
            self.print_btn.configure(state="disabled")
            return

        zoomed = img.resize(
            (img.width * PREVIEW_ZOOM, img.height * PREVIEW_ZOOM),
            Image.Resampling.NEAREST,
        )
        photo = ImageTk.PhotoImage(zoomed)
        self._preview_image_ref = photo
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, image=photo, anchor="nw")
        self.preview_canvas.configure(scrollregion=(0, 0, zoomed.width, zoomed.height))

        approx_mm = img.height / DOTS_PER_MM
        copies = max(1, self.doc.copies)
        copy_word = "copy" if copies == 1 else "copies"
        info = (f"{img.width}×{img.height} dots · {approx_mm:.1f} mm tall · "
                f"{len(self.doc.elements)} blocks · {copies} {copy_word}")
        if self.doc.sticker_height_mm > 0:
            info += f" · sticker {self.doc.sticker_height_mm:g} mm"
        self.preview_info_var.set(info)
        self.print_btn.configure(state=("normal" if self.doc.elements else "disabled"))


# --------------------------------------------------------------------------- #
# Entry                                                                       #
# --------------------------------------------------------------------------- #

def main() -> None:
    PRESETS_DIR.mkdir(exist_ok=True)
    LabelApp().mainloop()


if __name__ == "__main__":
    main()
