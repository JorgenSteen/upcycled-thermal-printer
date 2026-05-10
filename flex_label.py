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
    seg, gap = 8, 5
    x = 0
    while x < width_dots:
        x_end = min(x + seg, width_dots)
        draw.line([(x, y), (x_end, y)], fill=0, width=2)
        x += seg + gap
    return img


def render_label(doc: LabelDoc, font_family: str) -> Image.Image:
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
        help_menu.add_command(label="About", command=self._about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _about(self) -> None:
        messagebox.showinfo(
            "About Flex Label",
            "Flex Label — block-based designer for the Alere BTP-L560.\n\n"
            "Per-block formatting · QR · spacers · cut markers · live preview\n"
            "Presets save to ./presets/. Settings save to flex_label_settings.json.",
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
        tape.columnconfigure(1, weight=1)

        preset = ttk.LabelFrame(parent, text="Presets", padding=8)
        preset.pack(fill="x", pady=(0, 8))
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset, textvariable=self.preset_var, state="readonly")
        self.preset_combo.pack(fill="x", pady=2)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        btnrow = ttk.Frame(preset)
        btnrow.pack(fill="x", pady=2)
        ttk.Button(btnrow, text="Save", command=self.action_save_preset).pack(
            side="left", expand=True, fill="x", padx=(0, 2))
        ttk.Button(btnrow, text="Reload", command=self._refresh_preset_combo).pack(
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
        except (ValueError, TypeError, tk.TclError):
            return
        self.doc.h_align = self.h_align_var.get()
        self.refresh_preview()

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

    def _on_preset_selected(self, _event: object = None) -> None:
        name = self.preset_var.get()
        if not name:
            return
        path = PRESETS_DIR / f"{name}.json"
        if path.exists():
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
            img = render_label(self.doc, self.settings.default_font_family)
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
        self.preview_info_var.set(
            f"{img.width}×{img.height} dots · {approx_mm:.1f} mm tall · {len(self.doc.elements)} blocks"
        )
        self.print_btn.configure(state=("normal" if self.doc.elements else "disabled"))


# --------------------------------------------------------------------------- #
# Entry                                                                       #
# --------------------------------------------------------------------------- #

def main() -> None:
    PRESETS_DIR.mkdir(exist_ok=True)
    LabelApp().mainloop()


if __name__ == "__main__":
    main()
