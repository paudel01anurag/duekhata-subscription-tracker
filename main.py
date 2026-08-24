from __future__ import annotations

import calendar
import hashlib
import hmac
import os
import secrets
import shutil
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk
from tkinter import font as tkfont

from tkcalendar import DateEntry

from expense_tracker import (
    CADENCE_MONTHLY,
    CADENCE_ONCE,
    CADENCE_QUARTERLY,
    CADENCE_WEEKLY,
    CADENCE_YEARLY,
    next_occurrence,
    get_category_totals,
    get_totals_by,
    get_monthly_totals,
    get_upcoming,
    CADENCE_LABELS,
    CADENCE_MONTHLY,
    CADENCE_ONCE,
    CADENCES,
    LABELS_TO_CADENCE,
    create_schema,
    add_expense,
    create_expense,
    delete_expense,
    get_upcoming,
    get_yearly_total,
    update_expense,
    get_expenses_by_day,
    get_expenses_for_day,
    get_paid_expense_ids,
    get_monthly_run_rate,
    get_irregular_total_for_month,
    get_paid_total_for_month,
    get_total_for_month,
    load_expenses,
    clear_credentials,
    get_stored_credentials,
    save_credentials,
    set_expense_paid,
    card_due_date,
    create_card,
    delete_card,
    get_card_payments,
    get_cards_due_between,
    get_cards_due_in_month,
    load_cards,
    save_card,
    set_card_payment,
    get_card_payments_for_year,
    get_card_year_totals,
    KIND_BANK,
    KIND_CARD,
    KIND_LABELS,
    cards_only,
    expenses_charged_to,
    find_card,
    payment_source_name,
    subscription_run_rate_for_source,
)


APP_VERSION = "3.3.0"
APP_NAME = "DueKhata"
APP_DATA_FOLDER = "DueKhata"

# Folders used before the rename, checked once so an upgrade keeps its data.
PREVIOUS_APP_DATA_FOLDERS = ("SubscriptionTracker",)
AUTH_PASSWORD_ITERATIONS = 200_000
AUTH_PASSWORD_MIN_LENGTH = 8
AUTH_RECOVER_SENTINEL = "__subscription_tracker_recover__"


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except (ValueError, AttributeError):
        return None


def _adopt_previous_data_folder(app_data_directory: Path) -> None:
    """Carry data over from the folder used before the application was renamed.

    Someone upgrading from Subscription Tracker has their subscriptions under the
    old name. Without this the application would start empty and look as though
    their data had been lost. The old folder is copied rather than moved, so it
    stays behind as an accidental backup.
    """
    if (app_data_directory / "expenses.db").exists():
        return

    for previous_name in PREVIOUS_APP_DATA_FOLDERS:
        previous_directory = app_data_directory.parent / previous_name
        if previous_directory == app_data_directory or not previous_directory.is_dir():
            continue
        if not (previous_directory / "expenses.db").exists():
            continue
        for file_name in ("expenses.db", "expenses.json"):
            source_file = previous_directory / file_name
            if source_file.exists():
                shutil.copy2(source_file, app_data_directory / file_name)
        return


def get_app_data_file() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        app_data_directory = Path(local_app_data) / APP_DATA_FOLDER
    else:
        app_data_directory = Path.home() / ".duekhata"

    app_data_directory.mkdir(parents=True, exist_ok=True)
    source_directory = Path(__file__).resolve().parent
    database_file = app_data_directory / "expenses.db"

    _adopt_previous_data_folder(app_data_directory)

    # A packaged build must always start with an empty database. Seeding only
    # happens when running from source, so that no personal financial data or
    # stored credentials can ever travel inside a copy handed to someone else.
    if getattr(sys, "frozen", False):
        return database_file

    # Preserve existing development data on the first run after upgrading.
    for file_name in ("expenses.db", "expenses.json"):
        source_file = source_directory / file_name
        destination_file = app_data_directory / file_name
        if not destination_file.exists() and source_file.exists() and source_file.resolve() != destination_file.resolve():
            shutil.copy2(source_file, destination_file)

    return database_file


def _derive_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, AUTH_PASSWORD_ITERATIONS)
    return hashed.hex(), salt.hex()


def _is_strong_password(password: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if len(password) < AUTH_PASSWORD_MIN_LENGTH:
        errors.append(f"at least {AUTH_PASSWORD_MIN_LENGTH} characters")
    if not any(character.isupper() for character in password):
        errors.append("one capital letter")
    if not any(character.islower() for character in password):
        errors.append("one lower-case letter")
    if not any(character.isdigit() for character in password):
        errors.append("one number")
    if not any(not character.isalnum() for character in password):
        errors.append("one symbol")
    return not errors, errors


def _check_password(password: str, stored_hash: str, stored_salt: str, iterations: int = AUTH_PASSWORD_ITERATIONS) -> bool:
    try:
        decoded_salt = bytes.fromhex(stored_salt)
        compare_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            decoded_salt,
            iterations,
        ).hex()
        return hmac.compare_digest(stored_hash, compare_hash)
    except (TypeError, ValueError):
        return False


def _show_auth_dialog(root: tk.Tk, data_file: Path) -> str | None:
    while True:
        stored_credentials = get_stored_credentials(data_file)
        if stored_credentials is None:
            result = AuthDialog(root, data_file, is_setup=True).show()
        else:
            result = AuthDialog(root, data_file, is_setup=False, stored_username=stored_credentials[0]).show()

        if result == AUTH_RECOVER_SENTINEL:
            clear_credentials(data_file)
            continue

        if result is not None and result != "":
            return result
        return None


# ---------------------------------------------------------------------------
# Design tokens
#
# Typography, spacing and elevation follow one scale so that every surface in
# the application is built from the same vocabulary instead of ad-hoc numbers.
# ---------------------------------------------------------------------------

_FONT_TEXT = "Segoe UI"
_FONT_DISPLAY = "Segoe UI"
_FONT_ICON = ""

# Segoe Fluent Icons code points, used only when that font is installed.
ICON_CHEVRON_LEFT = chr(0xE76B)
ICON_CHEVRON_RIGHT = chr(0xE76C)
ICON_ADD = chr(0xE710)
ICON_LIGHT_MODE = chr(0xE706)
ICON_DARK_MODE = chr(0xE708)
ICON_PAID = chr(0xE73E)
ICON_DELETE = chr(0xE74D)
ICON_DASHBOARD = chr(0xE80F)
ICON_LIST = chr(0xE8FD)
ICON_CALENDAR = chr(0xE787)
ICON_STATS = chr(0xE9D9)
ICON_EDIT = chr(0xE70F)
ICON_CARD = chr(0xE8C7)

# Fallback glyphs for machines without the icon font.
ICON_FALLBACK = {
    ICON_CHEVRON_LEFT: "‹",
    ICON_CHEVRON_RIGHT: "›",
    ICON_ADD: "+",
    ICON_LIGHT_MODE: "☼",
    ICON_DARK_MODE: "☾",
    ICON_PAID: "✓",
    ICON_DELETE: "✕",
    ICON_DASHBOARD: "▦",
    ICON_LIST: "≡",
    ICON_CALENDAR: "▤",
    ICON_STATS: "▓",
    ICON_EDIT: "✎",
    ICON_CARD: "▭",
}

# 4px base grid.
SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_5, SPACE_6 = 4, 8, 12, 16, 20, 24

NAV_WIDTH = 196
DETAILS_WIDTH = 372

ALL_CATEGORIES = "All categories"
ALL_CADENCES = "Any"
NO_PAYMENT_SOURCE = "Not set"
# Day-list rows for cards carry this prefix so their ids can never collide with
# an expense id, which is what the edit and delete actions look up.
CARD_ROW_PREFIX = "card:"

# Chart colours, warm-leaning so they sit with the palette rather than fight it.
# Every card is drawn in the same blue. Cards are one kind of obligation, and
# giving each its own colour turned the calendar into confetti; colour is only
# worth spending where it distinguishes one category of spending from another.
CARD_COLOUR = "#5b8ac7"

CATEGORY_COLOURS = (
    "#b65f3c", "#5b8ac7", "#5aa469", "#c2557a",
    "#d9a441", "#3aa0b8", "#8a6bbf", "#7a8b4a",
)

RADIUS_CHIP = 8
RADIUS_CARD = 14
RADIUS_SHEET = 18


def resolve_fonts(root: tk.Misc) -> None:
    """Pick the best available font families once a Tk root exists."""
    global _FONT_TEXT, _FONT_DISPLAY, _FONT_ICON
    try:
        families = set(tkfont.families(root))
    except tk.TclError:
        return

    # Windows first, then the macOS system faces, then the common Linux ones.
    # Every list ends in a family Tk will always resolve to something sane.
    text_candidates = (
        "Segoe UI Variable Text", "Segoe UI",          # Windows 11 / 10
        "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue",  # macOS
        "Cantarell", "DejaVu Sans",                    # Linux
        "TkDefaultFont",
    )
    display_candidates = (
        "Segoe UI Variable Display", "Segoe UI",
        "SF Pro Display", ".AppleSystemUIFont", "Helvetica Neue",
        "Cantarell", "DejaVu Sans",
        "TkDefaultFont",
    )
    # No macOS or Linux equivalent ships the Fluent glyphs, so on those platforms
    # _FONT_ICON stays empty and icon() falls back to plain-text symbols.
    icon_candidates = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

    for candidate in text_candidates:
        if candidate in families:
            _FONT_TEXT = candidate
            break
    for candidate in display_candidates:
        if candidate in families:
            _FONT_DISPLAY = candidate
            break
    for candidate in icon_candidates:
        if candidate in families:
            _FONT_ICON = candidate
            break


def text_font(size: int, bold: bool = False) -> tuple:
    return (_FONT_TEXT, size, "bold") if bold else (_FONT_TEXT, size)


def display_font(size: int, bold: bool = True) -> tuple:
    return (_FONT_DISPLAY, size, "bold") if bold else (_FONT_DISPLAY, size)


def icon_font(size: int) -> tuple:
    return (_FONT_ICON, size) if _FONT_ICON else (_FONT_TEXT, size)


def icon(glyph: str) -> str:
    return glyph if _FONT_ICON else ICON_FALLBACK.get(glyph, glyph)


def _to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(base: str, other: str, amount: float) -> str:
    """Blend `other` into `base`. Tk has no alpha, so tints are pre-computed."""
    amount = max(0.0, min(1.0, amount))
    base_rgb = _to_rgb(base)
    other_rgb = _to_rgb(other)
    blended = tuple(round(a + (b - a) * amount) for a, b in zip(base_rgb, other_rgb))
    return "#%02x%02x%02x" % blended


def luminance(color: str) -> float:
    red, green, blue = (channel / 255 for channel in _to_rgb(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def readable_on(color: str, dark: str = "#2b1c14", light: str = "#fff8f3") -> str:
    return dark if luminance(color) > 0.55 else light


WARM_LIGHT = {
    "background": "#f6f1ed",
    "panel": "#eadfd7",
    "panel_alt": "#f8f2ee",
    "surface": "#fffbf8",
    "surface_1": "#fdf7f2",
    "surface_2": "#f8efe8",
    "surface_3": "#f2e6dd",
    "hero": "#674733",
    "hero_border": "#8b6650",
    "hero_text": "#fffaf6",
    "hero_text_secondary": "#eadbd0",
    "text": "#2e1e16",
    "text_secondary": "#6b564b",
    "text_muted": "#97847a",
    "accent": "#b65f3c",
    "accent_hover": "#994a2d",
    "on_accent": "#fffaf6",
    "accent_soft": "#f5e2d8",
    "positive": "#4f7a4a",
    "border": "#d5c1b5",
    "outline": "#dccabe",
    "outline_variant": "#ece0d7",
    "shadow": "#4a2c1c",
    "calendar_bg": "#f6f1ed",
    "calendar_cell": "#fffbf8",
    "calendar_selected": "#f7e3d8",
    "calendar_selected_border": "#b65f3c",
    "calendar_today": "#fdf3ec",
    "calendar_today_border": "#c88b64",
    "calendar_outside": "#f1eae5",
    "list_bg": "#fffbf8",
    "list_header": "#f6efea",
    "list_row_alt": "#fbf5f1",
    "list_selected": "#f2ddd1",
    "input_cursor": "#2e1e16",
    "header_control": "#674733",
    "header_control_hover": "#7c5540",
    "header_control_text": "#fffaf6",
    "header_field": "#fffbf8",
}

WARM_DARK = {
    "background": "#17100c",
    "panel": "#291f1a",
    "panel_alt": "#231a16",
    "surface": "#241a14",
    "surface_1": "#2b1f18",
    "surface_2": "#33251c",
    "surface_3": "#3b2b21",
    "hero": "#302318",
    "hero_border": "#6e5038",
    "hero_text": "#fffaf6",
    "hero_text_secondary": "#d9c4b5",
    "text": "#f4e9dd",
    "text_secondary": "#e3d1be",
    "text_muted": "#bfab98",
    "accent": "#ff9f43",
    "accent_hover": "#ffb162",
    "on_accent": "#241a15",
    "accent_soft": "#40291a",
    "positive": "#8bc48a",
    "border": "#553b2c",
    "outline": "#4d3728",
    "outline_variant": "#35271e",
    "shadow": "#000000",
    "calendar_bg": "#17100c",
    "calendar_cell": "#251b14",
    "calendar_selected": "#43301f",
    "calendar_selected_border": "#ff9f43",
    "calendar_today": "#2e2118",
    "calendar_today_border": "#a36f3f",
    "calendar_outside": "#1c1410",
    "list_bg": "#241a14",
    "list_header": "#2b1f18",
    "list_row_alt": "#281d16",
    "list_selected": "#4a3524",
    "input_cursor": "#ffffff",
    "header_control": "#5a3d2e",
    "header_control_hover": "#76513d",
    "header_control_text": "#fffaf6",
    "header_field": "#2d211b",
}


def draw_rounded_rect(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    fill: str,
    outline: str | None = None,
    width: int = 1,
    tags: tuple = (),
) -> None:
    # Fill the shape without outlining its overlapping pieces. Drawing the
    # border separately avoids visible seams across rounded cards and cells.
    radius = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    if fill:
        canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline="", tags=tags)
        canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline="", tags=tags)
        if radius:
            for x_start, y_start, start_angle in (
                (x1, y1, 90),
                (x2 - 2 * radius, y1, 0),
                (x1, y2 - 2 * radius, 180),
                (x2 - 2 * radius, y2 - 2 * radius, 270),
            ):
                canvas.create_arc(
                    x_start,
                    y_start,
                    x_start + 2 * radius,
                    y_start + 2 * radius,
                    start=start_angle,
                    extent=90,
                    style="pieslice",
                    fill=fill,
                    outline="",
                    tags=tags,
                )

    if not outline or width <= 0:
        return

    canvas.create_line(x1 + radius, y1, x2 - radius, y1, fill=outline, width=width, tags=tags)
    canvas.create_line(x2, y1 + radius, x2, y2 - radius, fill=outline, width=width, tags=tags)
    canvas.create_line(x1 + radius, y2, x2 - radius, y2, fill=outline, width=width, tags=tags)
    canvas.create_line(x1, y1 + radius, x1, y2 - radius, fill=outline, width=width, tags=tags)
    if radius:
        for x_start, y_start, start_angle in (
            (x1, y1, 90),
            (x2 - 2 * radius, y1, 0),
            (x1, y2 - 2 * radius, 180),
            (x2 - 2 * radius, y2 - 2 * radius, 270),
        ):
            canvas.create_arc(
                x_start,
                y_start,
                x_start + 2 * radius,
                y_start + 2 * radius,
                start=start_angle,
                extent=90,
                style="arc",
                outline=outline,
                width=width,
                tags=tags,
            )


def draw_elevation(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    behind: str,
    shadow: str,
    level: int = 1,
) -> None:
    """Approximate a Material drop shadow.

    The Tk canvas has no alpha channel, so each ring of the shadow is a rounded
    rectangle pre-blended against whatever sits behind the card. Rings are drawn
    outermost first so the darkest edge ends up nearest the card.
    """
    spread = 2 + level * 2
    strongest = 0.05 + 0.045 * level
    for ring in range(spread, 0, -1):
        strength = strongest * (1.0 - (ring - 1) / spread) ** 1.6
        draw_rounded_rect(
            canvas,
            x1 - ring,
            y1 - ring + level,
            x2 + ring,
            y2 + ring + level,
            radius + ring,
            mix(behind, shadow, strength),
        )


def draw_chip(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    fill: str,
    accent: str,
    label: str,
    text_color: str,
    font: tuple,
    trailing: str = "",
    trailing_color: str | None = None,
    tags: tuple = (),
) -> None:
    """A subscription pill: tinted body with a saturated leading bar."""
    height = y2 - y1
    radius = min(RADIUS_CHIP, height // 2)
    draw_rounded_rect(canvas, x1, y1, x2, y2, radius, fill, tags=tags)
    bar_width = 3
    draw_rounded_rect(canvas, x1, y1, x1 + bar_width * 2, y2, radius, accent, tags=tags)
    canvas.create_rectangle(x1 + bar_width, y1, x1 + bar_width * 2, y2, fill=fill, outline="", tags=tags)

    text_x = x1 + bar_width + 6
    canvas.create_text(
        text_x,
        (y1 + y2) // 2,
        text=label,
        anchor="w",
        fill=text_color,
        font=font,
        tags=tags,
    )
    if trailing:
        canvas.create_text(
            x2 - 6,
            (y1 + y2) // 2,
            text=trailing,
            anchor="e",
            fill=trailing_color or text_color,
            font=font,
            tags=tags,
        )


class _StatefulCanvasButton(tk.Canvas):
    """Shared hover / press plumbing for the canvas-drawn controls.

    ttk cannot round a corner or tint a control on hover without a themed
    element image, so the buttons that need a modern finish are painted by hand.
    """

    def __init__(self, master: tk.Misc, theme: dict, **kwargs) -> None:
        super().__init__(master, highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.theme = theme
        self.surface = theme["background"]
        self.enabled = True
        self._hovered = False
        self._pressed = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_theme(self, theme: dict, surface: str | None = None) -> None:
        self.theme = theme
        self.surface = surface or theme["background"]
        self.configure(bg=self.surface)
        self.redraw()

    def _on_enter(self, _event=None) -> None:
        self._hovered = True
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self.redraw()

    def _on_leave(self, _event=None) -> None:
        self._hovered = False
        self._pressed = False
        self.redraw()

    def _on_press(self, _event=None) -> None:
        if not self.enabled:
            return
        self._pressed = True
        self.redraw()

    def _on_release(self, _event=None) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.redraw()
        if was_pressed and self.enabled and self._hovered:
            self.invoke()

    def invoke(self) -> None:
        raise NotImplementedError

    def redraw(self) -> None:
        raise NotImplementedError

    def _state_overlay(self, base: str) -> str:
        """Material state layers: a tint of the foreground over the base."""
        if not self.enabled:
            return base
        if self._pressed:
            return mix(base, self.theme["text"], 0.16)
        if self._hovered:
            return mix(base, self.theme["text"], 0.08)
        return base


class IconButton(_StatefulCanvasButton):
    def __init__(
        self,
        master: tk.Misc,
        glyph: str,
        command,
        theme: dict,
        size: int = 38,
        variant: str = "ghost",
        glyph_size: int = 12,
    ) -> None:
        super().__init__(master, theme, width=size, height=size)
        self.glyph = glyph
        self.command = command
        self.size = size
        self.variant = variant
        self.glyph_size = glyph_size
        self.configure(bg=self.surface)
        self.redraw()

    def set_glyph(self, glyph: str) -> None:
        self.glyph = glyph
        self.redraw()

    def invoke(self) -> None:
        if self.command:
            self.command()

    def redraw(self) -> None:
        self.delete("all")
        theme = self.theme
        size = self.size
        if self.variant == "filled":
            base, foreground = theme["accent"], theme["on_accent"]
        elif self.variant == "tonal":
            base, foreground = theme["accent_soft"], theme["accent"]
        else:
            base, foreground = self.surface, theme["text_secondary"]

        fill = self._state_overlay(base)
        if self.variant == "ghost" and fill == self.surface:
            fill = self.surface
        self.create_oval(1, 1, size - 2, size - 2, fill=fill, outline="")
        if self.variant == "ghost" and (self._hovered or self._pressed):
            foreground = theme["text"]
        self.create_text(
            size // 2,
            size // 2,
            text=icon(self.glyph),
            fill=foreground,
            font=icon_font(self.glyph_size),
        )


class PillButton(_StatefulCanvasButton):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command,
        theme: dict,
        variant: str = "filled",
        glyph: str = "",
        height: int = 38,
        min_width: int = 0,
    ) -> None:
        super().__init__(master, theme, height=height)
        self.text = text
        self.command = command
        self.variant = variant
        self.glyph = glyph
        self.height = height
        self.min_width = min_width
        self._font = tkfont.Font(master, font=text_font(10, bold=True))
        self.configure(bg=self.surface)
        self._resize()
        self.redraw()

    def set_text(self, text: str, glyph: str = "") -> None:
        self.text = text
        if glyph:
            self.glyph = glyph
        self._resize()
        self.redraw()

    def _resize(self) -> None:
        width = self._font.measure(self.text) + SPACE_6
        if self.glyph:
            width += 22
        self.configure(width=max(self.min_width, width))

    def invoke(self) -> None:
        if self.command:
            self.command()

    def redraw(self) -> None:
        self.delete("all")
        theme = self.theme
        width = max(self.winfo_reqwidth(), 1)
        height = self.height
        if self.variant == "filled":
            base, foreground = theme["accent"], theme["on_accent"]
        elif self.variant == "tonal":
            base, foreground = theme["accent_soft"], theme["accent"]
        else:
            base, foreground = self.surface, theme["text_secondary"]

        fill = self._state_overlay(base)
        radius = height // 2
        outline = theme["outline"] if self.variant == "outlined" else None
        draw_rounded_rect(self, 1, 1, width - 2, height - 2, radius, fill, outline)

        text_x = width // 2
        if self.glyph:
            glyph_width = 18
            total = self._font.measure(self.text) + glyph_width
            start = (width - total) // 2
            self.create_text(
                start + glyph_width // 2,
                height // 2,
                text=icon(self.glyph),
                fill=foreground,
                font=icon_font(11),
            )
            text_x = start + glyph_width + self._font.measure(self.text) // 2
        self.create_text(text_x, height // 2, text=self.text, fill=foreground, font=text_font(10, bold=True))


class SegmentedControl(tk.Canvas):
    """A small row of mutually exclusive options, drawn as one pill."""

    def __init__(self, master: tk.Misc, options: tuple, command, theme: dict, height: int = 30) -> None:
        super().__init__(master, height=height, highlightthickness=0, bd=0, takefocus=0)
        self.options = options
        self.command = command
        self.theme = theme
        self.surface = theme["background"]
        self.height = height
        self.selected = options[0][0] if options else ""
        self._hovered = None
        self._font = tkfont.Font(master, font=text_font(9, bold=True))
        self._bounds: list = []
        self.configure(bg=self.surface, cursor="hand2")
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _event: self._set_hover(None))
        self._resize()
        self.redraw()

    def _resize(self) -> None:
        width = SPACE_1
        for _key, label in self.options:
            width += self._font.measure(label) + SPACE_5
        self.configure(width=width + SPACE_1)

    def set_theme(self, theme: dict, surface: str | None = None) -> None:
        self.theme = theme
        self.surface = surface or theme["background"]
        self.configure(bg=self.surface)
        self.redraw()

    def set_selected(self, key: str) -> None:
        self.selected = key
        self.redraw()

    def _hit(self, x: int):
        for key, x1, x2 in self._bounds:
            if x1 <= x <= x2:
                return key
        return None

    def _set_hover(self, key) -> None:
        if key != self._hovered:
            self._hovered = key
            self.redraw()

    def _on_motion(self, event) -> None:
        self._set_hover(self._hit(event.x))

    def _on_click(self, event) -> None:
        key = self._hit(event.x)
        if key and key != self.selected:
            self.selected = key
            self.redraw()
            if self.command:
                self.command(key)

    def redraw(self) -> None:
        self.delete("all")
        theme = self.theme
        width = max(self.winfo_reqwidth(), 1)
        height = self.height
        draw_rounded_rect(self, 0, 0, width - 1, height - 1, height // 2, theme["surface_2"])

        self._bounds = []
        x = SPACE_1
        for key, label in self.options:
            segment = self._font.measure(label) + SPACE_5
            if key == self.selected:
                draw_rounded_rect(
                    self, x, 3, x + segment, height - 4, (height - 7) // 2, theme["surface"]
                )
                colour = theme["accent"]
            elif key == self._hovered:
                colour = theme["text"]
            else:
                colour = theme["text_muted"]
            self.create_text(
                x + segment // 2, height // 2, text=label, fill=colour, font=text_font(9, bold=True)
            )
            self._bounds.append((key, x, x + segment))
            x += segment


class NavItem(_StatefulCanvasButton):
    """One row in the sidebar. Reads as a pill when it is the active view."""

    def __init__(self, master: tk.Misc, glyph: str, label: str, command, theme: dict) -> None:
        super().__init__(master, theme, height=42)
        self.glyph = glyph
        self.label = label
        self.command = command
        self.selected = False
        self.surface = theme["surface_1"]
        self.configure(bg=self.surface, width=NAV_WIDTH - SPACE_4)
        self.redraw()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.redraw()

    def invoke(self) -> None:
        if self.command:
            self.command()

    def redraw(self) -> None:
        self.delete("all")
        theme = self.theme
        width = max(self.winfo_reqwidth(), 1)
        height = 42

        if self.selected:
            fill = theme["accent_soft"]
            foreground = theme["accent"]
        else:
            fill = self._state_overlay(self.surface)
            foreground = theme["text_secondary"] if not self._hovered else theme["text"]

        if fill != self.surface or self.selected:
            draw_rounded_rect(self, 2, 3, width - 3, height - 4, RADIUS_CHIP + 2, fill)

        self.create_text(
            SPACE_3 + 4,
            height // 2,
            text=icon(self.glyph),
            anchor="w",
            fill=foreground,
            font=icon_font(12),
        )
        self.create_text(
            SPACE_3 + 28,
            height // 2,
            text=self.label,
            anchor="w",
            fill=foreground,
            font=text_font(10, bold=self.selected),
        )


class AuthDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        data_file: Path,
        is_setup: bool = True,
        stored_username: str = "",
    ) -> None:
        super().__init__(master)
        self.data_file = data_file
        self.is_setup = is_setup
        self.stored_username = stored_username
        self.result: str | None = None

        self.title("Create account" if self.is_setup else "Log in")
        self.configure(bg=WARM_DARK["background"])
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda _event: self._on_cancel())
        self.bind("<Return>", lambda _event: self._submit())
        self._build_ui()
        self._apply_layout()
        self._show_password.set(False)
        self._sync_password_visibility()

    def _build_ui(self) -> None:
        container = tk.Frame(self, bg=WARM_DARK["surface_1"])
        container.pack(fill="both", expand=True, padx=20, pady=20)
        container.columnconfigure(0, weight=1)

        stored_name = (self.stored_username or "").strip()
        display_name = (stored_name[:1].upper() + stored_name[1:]) if stored_name else "user"
        title_text = "Set your account password" if self.is_setup else f"Welcome back, {display_name}"
        tk.Label(
            container,
            text=title_text,
            fg=WARM_DARK["hero_text"],
            bg=WARM_DARK["surface_1"],
            font=display_font(17),
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self._show_password = tk.BooleanVar(value=False)

        tk.Label(container, text="Username", fg=WARM_DARK["text_secondary"], bg=WARM_DARK["surface_1"], font=text_font(9, bold=True)).grid(
            row=1, column=0, sticky="w", pady=(12, 4)
        )
        self.username_var = tk.StringVar(value=self.stored_username)
        self.username_entry = tk.Entry(
            container,
            textvariable=self.username_var,
            width=32,
            font=text_font(11),
            bg=WARM_DARK["surface_2"],
            fg=WARM_DARK["text"],
            insertbackground=WARM_DARK["input_cursor"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=WARM_DARK["outline"],
            highlightcolor=WARM_DARK["accent"],
            readonlybackground=WARM_DARK["surface_3"],
            disabledforeground=WARM_DARK["text_secondary"],
            exportselection=False,
        )
        self.username_entry.grid(row=2, column=0, sticky="ew")
        if not self.is_setup:
            self.username_entry.configure(state="readonly")

        tk.Label(container, text="Password", fg=WARM_DARK["text_secondary"], bg=WARM_DARK["surface_1"], font=text_font(9, bold=True)).grid(
            row=3, column=0, sticky="w", pady=(12, 4)
        )
        self.password_var = tk.StringVar()
        self.password_entry = tk.Entry(
            container,
            textvariable=self.password_var,
            show="*",
            width=32,
            font=text_font(11),
            bg=WARM_DARK["surface_2"],
            fg=WARM_DARK["text"],
            insertbackground=WARM_DARK["input_cursor"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=WARM_DARK["outline"],
            highlightcolor=WARM_DARK["accent"],
            exportselection=False,
        )
        self.password_entry.grid(row=4, column=0, sticky="ew")

        if self.is_setup:
            tk.Label(container, text="Confirm password", fg=WARM_DARK["text_secondary"], bg=WARM_DARK["surface_1"], font=text_font(9, bold=True)).grid(
                row=5, column=0, sticky="w", pady=(12, 4)
            )
            self.confirm_var = tk.StringVar()
            self.confirm_entry = tk.Entry(
                container,
                textvariable=self.confirm_var,
                show="*",
                width=32,
                font=text_font(11),
                bg=WARM_DARK["surface_2"],
                fg=WARM_DARK["text"],
                insertbackground=WARM_DARK["input_cursor"],
                relief="flat",
                highlightthickness=1,
                highlightbackground=WARM_DARK["outline"],
                highlightcolor=WARM_DARK["accent"],
                exportselection=False,
            )
            self.confirm_entry.grid(row=6, column=0, sticky="ew")
            hint = "Must contain at least 8 chars, 1 uppercase, 1 lowercase, 1 digit, 1 symbol."
            tk.Label(
                container,
                text=hint,
                fg=WARM_DARK["text_secondary"],
                bg=WARM_DARK["surface_1"],
                font=text_font(9),
                wraplength=360,
                justify="left",
            ).grid(row=7, column=0, sticky="w", pady=(8, 8))
            focus_target = self.password_entry
            self.confirm_row = 6
        else:
            self.confirm_var = tk.StringVar()
            self.confirm_entry = None
            self.confirm_row = None
            focus_target = self.password_entry

        footer = tk.Frame(container, bg=WARM_DARK["surface_1"])
        footer.grid(row=(self.confirm_row or 4) + 2, column=0, sticky="ew", pady=(2, 0))
        footer.columnconfigure(0, weight=1)

        # This dialog runs before the app configures ttk, and the native
        # indicator ignores selectcolor, so style a dark checkbutton here.
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Auth.TCheckbutton",
            background=WARM_DARK["surface_1"],
            foreground=WARM_DARK["text"],
            focuscolor=WARM_DARK["surface_1"],
            indicatorbackground=WARM_DARK["surface_2"],
            indicatorforeground=WARM_DARK["on_accent"],
            bordercolor=WARM_DARK["outline"],
            lightcolor=WARM_DARK["surface_2"],
            darkcolor=WARM_DARK["surface_2"],
            font=text_font(10),
        )
        style.map(
            "Auth.TCheckbutton",
            background=[("active", WARM_DARK["surface_1"])],
            indicatorbackground=[("selected", WARM_DARK["accent"])],
            bordercolor=[("selected", WARM_DARK["accent"])],
        )
        ttk.Checkbutton(
            footer,
            text="Show password",
            variable=self._show_password,
            command=self._sync_password_visibility,
            style="Auth.TCheckbutton",
        ).grid(row=0, column=0, sticky="w")

        self.message_var = tk.StringVar()
        tk.Label(
            container,
            textvariable=self.message_var,
            fg="#ff9e9e",
            bg=WARM_DARK["surface_1"],
            font=text_font(9),
            wraplength=360,
            justify="left",
        ).grid(row=(self.confirm_row or 4) + 3, column=0, sticky="w")

        action_area = tk.Frame(container, bg=WARM_DARK["surface_1"])
        action_area.grid(row=(self.confirm_row or 4) + 4, column=0, sticky="e", pady=(12, 0))
        if not self.is_setup:
            PillButton(
                action_area,
                "Recover account",
                self._request_recovery,
                WARM_DARK,
                variant="outlined",
            ).pack(side="left", padx=(0, SPACE_2))
        PillButton(
            action_area,
            "Cancel",
            self._on_cancel,
            WARM_DARK,
            variant="tonal",
        ).pack(side="left", padx=(0, SPACE_2))
        self._primary_button = PillButton(
            action_area,
            "Create account" if self.is_setup else "Log in",
            self._submit,
            WARM_DARK,
            variant="filled",
        )
        self._primary_button.pack(side="left")
        focus_target.focus_set()

    def _apply_layout(self) -> None:
        self.update_idletasks()
        width = max(420, self.winfo_reqwidth())
        height = max(self.winfo_reqheight(), 260)
        x_position = max(0, (self.winfo_screenwidth() - width) // 2)
        y_position = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x_position}+{y_position}")
        # Tk withdraws a transient window whenever its master is withdrawn. The login
        # dialog runs before the main window is shown, so marking it transient here
        # would unmap it and leave the process waiting on a window nobody can see.
        if self.master is not None and self.master.winfo_viewable():
            self.transient(self.master)
        self.deiconify()
        self.lift()
        self.grab_set()
        self.focus_force()

    def _sync_password_visibility(self) -> None:
        char = "" if self._show_password.get() else "*"
        self.password_entry.config(show=char)
        if self.is_setup and self.confirm_entry is not None:
            self.confirm_entry.config(show=char)

    def _set_error(self, message: str) -> None:
        self.message_var.set(message)

    def _submit(self) -> None:
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username:
            self._set_error("Please enter a username.")
            return

        if self.is_setup:
            confirm = self.confirm_var.get()
            if password != confirm:
                self._set_error("Password fields do not match.")
                return

            is_ok, missing = _is_strong_password(password)
            if not is_ok:
                self._set_error("Password requires: " + ", ".join(missing))
                return

            password_hash, salt = _derive_password(password)
            save_credentials(self.data_file, username, password_hash, salt, AUTH_PASSWORD_ITERATIONS)
            self.result = username
            self.destroy()
            return

        stored = get_stored_credentials(self.data_file)
        if stored is None:
            # Flipping is_setup in place would leave the login layout on screen without a
            # confirm field, so every later submit would fail the match check. Close instead
            # and let the caller reopen the dialog in setup mode.
            self.result = AUTH_RECOVER_SENTINEL
            self.destroy()
            return

        stored_username, stored_hash, stored_salt, _stored_iterations = stored
        if username != stored_username or not _check_password(password, stored_hash, stored_salt, _stored_iterations):
            self._set_error("Invalid username or password.")
            self.password_var.set("")
            self.password_entry.focus_set()
            return

        self.result = username
        self.destroy()

    def _request_recovery(self) -> None:
        proceed = messagebox.askyesno(
            "Recover account",
            "This will remove the existing login and let you set a new username and password.\n"
            "Stored subscriptions are not deleted.\n\nDo you want to continue?",
        )
        if not proceed:
            return

        self.result = AUTH_RECOVER_SENTINEL
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.result


class ExpenseTrackerApp:
    def __init__(self, root: tk.Tk, data_file: Path, username: str | None = None) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1360x880")
        self.root.minsize(1120, 740)
        self.root.configure(bg=WARM_LIGHT["background"])

        self.data_file = data_file
        self.authenticated_username = username or ""
        self.expenses = load_expenses(self.data_file)
        self.cards = load_cards(self.data_file)
        self.current_date = date.today().replace(day=1)
        self.selected_date = date.today()
        self.theme_mode = tk.StringVar(value="light")
        self.paid_expense_ids: set[str] = set()
        self.day_summary_text = ""
        resolve_fonts(self.root)
        self.calendar_font = tkfont.Font(self.root, font=text_font(8))
        self.themed_buttons: list[_StatefulCanvasButton] = []
        self.chart_style = "donut"
        self.stat_values = {"projected": 0.0, "remaining": 0.0, "paid": 0.0, "yearly": 0.0}
        self._apply_theme()

        self.build_ui()
        self.refresh_view()

    def _apply_theme(self) -> None:
        theme = self._theme()
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure("TFrame", background=theme["background"])
        style.configure("TLabel", background=theme["background"], foreground=theme["text"], font=text_font(10))
        style.configure("Muted.TLabel", background=theme["background"], foreground=theme["text_secondary"], font=text_font(9))
        style.configure("Section.TLabel", background=theme["background"], foreground=theme["text"], font=text_font(12, bold=True))

        # Text fields: a hairline outline that turns accent on focus.
        style.configure(
            "TEntry",
            fieldbackground=theme["surface"],
            foreground=theme["text"],
            insertcolor=theme["input_cursor"],
            bordercolor=theme["outline"],
            lightcolor=theme["outline"],
            darkcolor=theme["outline"],
            borderwidth=1,
            relief="flat",
            padding=(10, 7),
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", theme["accent"])],
            lightcolor=[("focus", theme["accent"])],
            darkcolor=[("focus", theme["accent"])],
        )

        # The combobox is filled rather than outlined: clam draws the same border
        # around the field and the arrow, so an outline would bevel the arrow too.
        style.configure(
            "TCombobox",
            fieldbackground=theme["surface_2"],
            background=theme["surface_2"],
            foreground=theme["text"],
            insertcolor=theme["input_cursor"],
            bordercolor=theme["surface_2"],
            lightcolor=theme["surface_2"],
            darkcolor=theme["surface_2"],
            arrowcolor=theme["text_secondary"],
            borderwidth=1,
            relief="flat",
            padding=(10, 7),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", theme["surface_2"]), ("hover", theme["surface_3"])],
            background=[("readonly", theme["surface_2"]), ("active", theme["surface_3"])],
            bordercolor=[("focus", theme["accent"])],
            lightcolor=[("focus", theme["accent"])],
            darkcolor=[("focus", theme["accent"])],
            arrowcolor=[("active", theme["text"])],
            foreground=[("readonly", theme["text"])],
        )

        # The combobox popup is a classic Tk listbox and needs option-database colours.
        self.root.option_add("*TCombobox*Listbox.background", theme["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", theme["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", theme["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", theme["on_accent"])
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)

        # Treeview: strip the sunken border, drop the bevelled headings, give rows room.
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Treeview",
            background=theme["list_bg"],
            fieldbackground=theme["list_bg"],
            foreground=theme["text"],
            borderwidth=0,
            relief="flat",
            rowheight=36,
            font=text_font(10),
        )
        style.configure(
            "Treeview.Heading",
            background=theme["background"],
            foreground=theme["text_muted"],
            relief="flat",
            borderwidth=0,
            padding=(10, 6),
            font=text_font(9, bold=True),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", theme["background"])],
            foreground=[("active", theme["text_secondary"])],
        )
        style.map(
            "Treeview",
            background=[("selected", theme["list_selected"])],
            foreground=[("selected", theme["text"])],
        )

        # Drop the stepper arrows so only a thumb remains, as on mobile.
        style.layout(
            "Vertical.TScrollbar",
            [(
                "Vertical.Scrollbar.trough",
                {"sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]},
            )],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=theme["outline"],
            troughcolor=theme["background"],
            bordercolor=theme["background"],
            lightcolor=theme["outline"],
            darkcolor=theme["outline"],
            arrowcolor=theme["text_muted"],
            borderwidth=0,
            relief="flat",
            width=8,
        )
        style.map("Vertical.TScrollbar", background=[("active", theme["accent"])])

        style.configure(
            "TCheckbutton",
            background=theme["background"],
            foreground=theme["text"],
            focuscolor=theme["background"],
            indicatorbackground=theme["surface"],
            indicatorforeground=theme["on_accent"],
            bordercolor=theme["outline"],
            lightcolor=theme["surface"],
            darkcolor=theme["surface"],
            padding=(2, 5),
            font=text_font(10),
        )
        style.map(
            "TCheckbutton",
            background=[("active", theme["background"])],
            indicatorbackground=[("selected", theme["accent"]), ("active", theme["surface_2"])],
            bordercolor=[("selected", theme["accent"])],
        )

        style.configure("Card.TFrame", background=theme["surface"], relief="flat")
        style.configure("Card.TLabel", background=theme["surface"], foreground=theme["text"], font=text_font(10))

        style.configure(
            "TButton",
            padding=(14, 8),
            background=theme["surface_2"],
            foreground=theme["text"],
            borderwidth=0,
            relief="flat",
            font=text_font(10),
        )
        style.map(
            "TButton",
            background=[("active", theme["surface_3"]), ("pressed", theme["surface_3"])],
            foreground=[("active", theme["text"])],
        )

        self.root.option_add("*insertBackground", theme["input_cursor"])
        self.root.configure(bg=theme["background"])
        for button in getattr(self, "themed_buttons", []):
            button.set_theme(theme)

    def _theme(self) -> dict[str, str]:
        return WARM_DARK if self.theme_mode.get() == "dark" else WARM_LIGHT

    def toggle_theme(self) -> None:
        self.theme_mode.set("dark" if self.theme_mode.get() == "light" else "light")
        self._apply_theme()
        self._refresh_theme_button()
        self.refresh_view()

    def _draw_stat_cards(self) -> None:
        """Three elevated cards: projected, remaining, and paid this month."""
        if not hasattr(self, "stats_canvas"):
            return
        theme = self._theme()
        self.stats_canvas.configure(bg=theme["background"])
        self.stats_canvas.delete("all")
        width = max(self.stats_canvas.winfo_width(), 1)
        height = max(self.stats_canvas.winfo_height(), 1)

        irregular_amount, irregular_kinds = getattr(self, "irregular_this_month", (0.0, []))
        if irregular_amount:
            note = "incl. $" + format(irregular_amount, ",.2f") + " " + " and ".join(irregular_kinds)
        else:
            note = ""

        # Two questions, two numbers. "Projected" is what leaves the account
        # this month; "average per month" is what the subscriptions cost to
        # run. A month holding a yearly renewal is higher than average and
        # says so rather than looking like a mistake.
        cards = [
            ("PROJECTED THIS MONTH", self.stat_values["projected"], theme["text"], note),
            ("AVERAGE PER MONTH", self.stat_values["run_rate"], theme["text_secondary"], "spread over the year"),
            ("REMAINING", self.stat_values["remaining"], theme["accent"], ""),
            ("PAID", self.stat_values["paid"], theme["positive"], ""),
            (f"TOTAL IN {self.current_date.year}", self.stat_values["yearly"], theme["text_secondary"], ""),
        ]
        gap = SPACE_3
        card_width = (width - gap * (len(cards) - 1) - 2) // len(cards)
        top = 5
        bottom = height - 7

        for index, (label, value, value_color, caption) in enumerate(cards):
            x1 = 1 + index * (card_width + gap)
            x2 = x1 + card_width
            draw_elevation(self.stats_canvas, x1, top, x2, bottom, RADIUS_CARD, theme["background"], theme["shadow"], level=1)
            draw_rounded_rect(
                self.stats_canvas,
                x1,
                top,
                x2,
                bottom,
                RADIUS_CARD,
                theme["surface"],
                theme["outline_variant"],
            )
            self.stats_canvas.create_text(
                x1 + SPACE_4,
                top + SPACE_4,
                text=label,
                anchor="nw",
                fill=theme["text_muted"],
                font=text_font(8, bold=True),
            )
            self.stats_canvas.create_text(
                x1 + SPACE_4,
                top + SPACE_4 + 15,
                text=f"${value:,.2f}",
                anchor="nw",
                fill=value_color,
                font=display_font(19),
            )
            if caption:
                self.stats_canvas.create_text(
                    x1 + SPACE_4,
                    top + SPACE_4 + 44,
                    text=caption,
                    anchor="nw",
                    fill=theme["text_muted"],
                    font=text_font(8),
                )

    def _draw_day_summary_card(self) -> None:
        if not hasattr(self, "day_summary_canvas"):
            return
        theme = self._theme()
        self.day_summary_canvas.configure(bg=theme["background"])
        self.day_summary_canvas.delete("all")
        width = max(self.day_summary_canvas.winfo_width(), 1)
        height = max(self.day_summary_canvas.winfo_height(), 1)
        draw_rounded_rect(
            self.day_summary_canvas,
            1,
            1,
            width - 2,
            height - 2,
            (height - 2) // 2,
            theme["surface_2"],
        )
        self.day_summary_canvas.create_text(
            SPACE_4,
            height // 2,
            text=self.day_summary_text,
            anchor="w",
            fill=theme["text_secondary"],
            font=text_font(9),
        )

    def _refresh_theme_button(self) -> None:
        if not hasattr(self, "theme_button"):
            return
        self.theme_button.set_glyph(ICON_DARK_MODE if self.theme_mode.get() == "light" else ICON_LIGHT_MODE)

    def _display_name(self) -> str:
        """Show the stored username with a capital first letter, leaving any
        deliberate inner capitals (for example "McKay") untouched."""
        name = self.authenticated_username.strip()
        return name[:1].upper() + name[1:] if name else ""

    def _welcome_text(self) -> str:
        if self.authenticated_username:
            return f"Welcome back, {self._display_name()}  ·  {date.today().strftime('%A, %B %d, %Y')}"
        return f"{date.today().strftime('%A, %B %d, %Y')}"

    # ------------------------------------------------------------------
    # Layout
    #
    # A sidebar selects one of five views, which are stacked in the same grid
    # cell and raised as needed. The month totals are
    # shared chrome, so they live outside the views and stay put while switching.
    # ------------------------------------------------------------------

    VIEWS = (
        ("dashboard", ICON_DASHBOARD, "Dashboard"),
        ("subscriptions", ICON_LIST, "Subscriptions"),
        ("cards", ICON_CARD, "Cards"),
        ("calendar", ICON_CALENDAR, "Calendar"),
        ("statistics", ICON_STATS, "Statistics"),
    )

    def build_ui(self) -> None:
        theme = self._theme()
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.themed_buttons = []
        # Plain tk.Labels placed in a view are built once and never rebuilt, so
        # the theme sweep below has no way to find them. Registering them with
        # the palette key their text uses keeps them in step.
        self.themed_labels = []
        self._build_sidebar(theme)

        content = tk.Frame(self.root, bg=theme["background"])
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        self.content_frame = content

        self._build_topbar(content, theme)

        self.view_container = tk.Frame(content, bg=theme["background"])
        self.view_container.grid(row=2, column=0, sticky="nsew", padx=SPACE_6, pady=(0, SPACE_5))
        self.view_container.columnconfigure(0, weight=1)
        self.view_container.rowconfigure(0, weight=1)

        self.views = {}
        self._build_dashboard_view(theme)
        self._build_subscriptions_view(theme)
        self._build_cards_view(theme)
        self._build_calendar_view(theme)
        self._build_statistics_view(theme)
        self.show_view("dashboard")

    def _build_sidebar(self, theme: dict) -> None:
        rail = tk.Frame(self.root, bg=theme["surface_1"], width=NAV_WIDTH)
        rail.grid(row=0, column=0, sticky="nsw")
        rail.grid_propagate(False)
        rail.columnconfigure(0, weight=1)
        rail.rowconfigure(2, weight=1)
        self.sidebar = rail

        brand = tk.Canvas(rail, height=76, bg=theme["surface_1"], highlightthickness=0)
        brand.grid(row=0, column=0, sticky="ew", padx=SPACE_2, pady=(SPACE_2, 0))
        brand.bind("<Configure>", lambda _event: self._draw_brand())
        self.brand_canvas = brand

        nav = tk.Frame(rail, bg=theme["surface_1"])
        nav.grid(row=1, column=0, sticky="ew", padx=SPACE_2, pady=(SPACE_2, 0))
        nav.columnconfigure(0, weight=1)

        self.nav_items = {}
        for index, (key, glyph, label) in enumerate(self.VIEWS):
            item = NavItem(nav, glyph, label, lambda name=key: self.show_view(name), theme)
            item.grid(row=index, column=0, sticky="ew", pady=1)
            self.nav_items[key] = item
            self.themed_buttons.append(item)

        footer = tk.Frame(rail, bg=theme["surface_1"])
        footer.grid(row=3, column=0, sticky="ew", padx=SPACE_3, pady=SPACE_3)
        footer.columnconfigure(0, weight=1)

        self.user_canvas = tk.Canvas(footer, height=34, bg=theme["surface_1"], highlightthickness=0)
        self.user_canvas.grid(row=0, column=0, sticky="ew", padx=(0, SPACE_1))
        self.user_canvas.bind("<Configure>", lambda _event: self._draw_user())

        self.theme_button = IconButton(footer, ICON_DARK_MODE, self.toggle_theme, theme, variant="tonal")
        self.theme_button.grid(row=0, column=1, sticky="e")
        self.themed_buttons.append(self.theme_button)

    def _build_topbar(self, parent: tk.Frame, theme: dict) -> None:
        bar = tk.Frame(parent, bg=theme["background"])
        bar.grid(row=0, column=0, sticky="ew", padx=SPACE_6, pady=(SPACE_5, SPACE_2))
        bar.columnconfigure(1, weight=1)
        self.topbar = bar

        self.view_title = ttk.Label(bar, text="Dashboard", font=display_font(21))
        self.view_title.grid(row=0, column=0, sticky="w")

        controls = tk.Frame(bar, bg=theme["background"])
        controls.grid(row=0, column=2, sticky="e")

        self.add_button = PillButton(controls, "Add payment", self.open_add_dialog, theme, glyph=ICON_ADD)
        self.add_button.grid(row=0, column=0)
        self.themed_buttons.append(self.add_button)

        self.subtitle_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.subtitle_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

    def _new_view(self, name: str, theme: dict) -> tk.Frame:
        frame = tk.Frame(self.view_container, bg=theme["background"])
        frame.grid(row=0, column=0, sticky="nsew")
        self.views[name] = frame
        return frame

    def show_view(self, name: str) -> None:
        self.active_view = name
        self.views[name].tkraise()
        for key, item in self.nav_items.items():
            item.set_selected(key == name)
        titles = {key: label for key, _glyph, label in self.VIEWS}
        self.view_title.config(text=titles.get(name, name.title()))
        # The Cards view has its own Add card button. Leaving "Add payment" in
        # the header there would put two different "add" buttons on one screen,
        # one of which quietly creates a subscription.
        if name == "cards":
            self.add_button.grid_remove()
        else:
            self.add_button.grid()
        self.refresh_view()

    # --- dashboard ----------------------------------------------------
    def _build_dashboard_view(self, theme: dict) -> None:
        view = self._new_view("dashboard", theme)
        view.columnconfigure(0, weight=3)
        view.columnconfigure(1, weight=2)
        view.rowconfigure(1, weight=1)

        self.stats_canvas = tk.Canvas(view, height=92, bg=theme["background"], highlightthickness=0)
        self.stats_canvas.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.stats_canvas.bind("<Configure>", lambda _event: self._draw_stat_cards())

        self.category_canvas = tk.Canvas(view, bg=theme["background"], highlightthickness=0)
        self.category_canvas.grid(row=1, column=0, sticky="nsew", padx=(0, SPACE_4), pady=(SPACE_4, 0))
        self.category_canvas.bind("<Configure>", lambda _event: self._draw_category_chart())

        self.upcoming_canvas = tk.Canvas(view, bg=theme["background"], highlightthickness=0)
        self.upcoming_canvas.grid(row=1, column=1, sticky="nsew", pady=(SPACE_4, 0))
        self.upcoming_canvas.bind("<Configure>", lambda _event: self._draw_upcoming())

        self.dash_trend_canvas = tk.Canvas(view, height=178, bg=theme["background"], highlightthickness=0)
        self.dash_trend_canvas.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(SPACE_4, 0))
        self.dash_trend_canvas.bind(
            "<Configure>", lambda _event: self._draw_trend_chart(self.dash_trend_canvas)
        )

    # --- subscriptions ------------------------------------------------
    def _build_subscriptions_view(self, theme: dict) -> None:
        view = self._new_view("subscriptions", theme)
        view.columnconfigure(0, weight=1)
        view.rowconfigure(1, weight=1)

        filters = tk.Frame(view, bg=theme["background"])
        filters.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, SPACE_3))
        filters.columnconfigure(5, weight=1)

        ttk.Label(filters, text="Search", style="Muted.TLabel").grid(row=0, column=0, padx=(0, SPACE_2))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self.populate_all_list())
        search_entry = tk.Entry(
            filters, textvariable=self.search_var, width=22,
            bg=theme["surface"], fg=theme["text"], font=text_font(10),
            insertbackground=theme["input_cursor"], relief="flat",
            highlightthickness=1, highlightbackground=theme["outline"],
            highlightcolor=theme["accent"],
        )
        search_entry.grid(row=0, column=1, padx=(0, SPACE_4), ipady=5)

        ttk.Label(filters, text="Category", style="Muted.TLabel").grid(row=0, column=2, padx=(0, SPACE_2))
        self.category_filter = tk.StringVar(value=ALL_CATEGORIES)
        self.category_box = ttk.Combobox(
            filters, textvariable=self.category_filter, state="readonly",
            width=15, font=text_font(10),
        )
        self.category_box.grid(row=0, column=3, padx=(0, SPACE_4))
        self.category_box.bind("<<ComboboxSelected>>", lambda _event: self.populate_all_list())

        ttk.Label(filters, text="Repeats", style="Muted.TLabel").grid(row=0, column=4, padx=(0, SPACE_2))
        self.cadence_filter = tk.StringVar(value=ALL_CADENCES)
        cadence_box = ttk.Combobox(
            filters, textvariable=self.cadence_filter, state="readonly",
            width=12, font=text_font(10),
            values=(ALL_CADENCES,) + tuple(self.CADENCE_LABELS.values()),
        )
        cadence_box.grid(row=0, column=5, sticky="w")
        cadence_box.bind("<<ComboboxSelected>>", lambda _event: self.populate_all_list())

        self.result_label = ttk.Label(filters, text="", style="Muted.TLabel")
        self.result_label.grid(row=0, column=6, sticky="e")

        self.all_list = ttk.Treeview(
            view,
            columns=("description", "amount", "cadence", "next", "category", "source"),
            show="headings",
        )
        headings = (
            ("description", "DESCRIPTION", 250, "w", True),
            ("amount", "AMOUNT", 95, "e", False),
            ("cadence", "REPEATS", 100, "w", False),
            ("next", "NEXT DUE", 115, "w", False),
            ("category", "CATEGORY", 130, "w", False),
            ("source", "CHARGED TO", 150, "w", False),
        )
        for key, title, width, anchor, stretch in headings:
            self.all_list.heading(key, text=title, anchor=anchor)
            self.all_list.column(key, width=width, minwidth=70, anchor=anchor, stretch=stretch)
        self.all_list.grid(row=1, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(view, orient="vertical", command=self.all_list.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.all_list.configure(yscrollcommand=scrollbar.set)
        self.all_list.bind("<Double-1>", self.edit_from_all_list)

        actions = tk.Frame(view, bg=theme["background"])
        actions.grid(row=2, column=0, columnspan=2, sticky="e", pady=(SPACE_3, 0))
        self.all_edit_button = PillButton(
            actions, "Edit", self.edit_from_all_list, theme, variant="tonal", glyph=ICON_EDIT
        )
        self.all_edit_button.grid(row=0, column=0, padx=(0, SPACE_2))
        self.all_delete_button = PillButton(
            actions, "Delete", self.delete_from_all_list, theme, variant="outlined", glyph=ICON_DELETE
        )
        self.all_delete_button.grid(row=0, column=1)
        self.themed_buttons.extend([self.all_edit_button, self.all_delete_button])

    # --- cards --------------------------------------------------------
    #
    # A card payment is a settlement, not a purchase. Everything here is kept
    # out of the spending totals on purpose; see the note in expense_tracker.

    def _build_cards_view(self, theme: dict) -> None:
        view = self._new_view("cards", theme)
        view.columnconfigure(0, weight=1)
        view.rowconfigure(3, weight=1)

        intro = tk.Label(
            view,
            text=(
                "Cards are tracked for their due date, not their cost. What you pay here settles "
                "purchases already listed under Subscriptions, so it is never added to your spending."
            ),
            bg=theme["background"],
            fg=theme["text_muted"],
            font=text_font(10),
            justify="left",
            anchor="w",
            wraplength=760,
        )
        intro.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, SPACE_3))
        self.themed_labels.append((intro, "text_muted"))

        self.card_stats_canvas = tk.Canvas(view, height=92, bg=theme["background"], highlightthickness=0)
        self.card_stats_canvas.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, SPACE_3))
        self.card_stats_canvas.bind("<Configure>", lambda _event: self._draw_card_stats())

        self.cards_summary = ttk.Label(view, text="", style="Muted.TLabel")
        self.cards_summary.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, SPACE_2))

        self.cards_list = ttk.Treeview(
            view,
            columns=("name", "kind", "due", "subs", "this_month", "last_month", "change", "year"),
            show="headings",
        )
        headings = (
            ("name", "NAME", 190, "w", True),
            ("kind", "KIND", 105, "w", False),
            ("due", "DUE", 90, "w", False),
            ("subs", "SUBSCRIPTIONS", 145, "e", False),
            ("this_month", "THIS MONTH", 110, "e", False),
            ("last_month", "LAST MONTH", 110, "e", False),
            ("change", "VS LAST MONTH", 120, "e", False),
            ("year", "PAID THIS YEAR", 120, "e", False),
        )
        for key, title, width, anchor, stretch in headings:
            self.cards_list.heading(key, text=title, anchor=anchor)
            self.cards_list.column(key, width=width, minwidth=80, anchor=anchor, stretch=stretch)
        self.cards_list.grid(row=3, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(view, orient="vertical", command=self.cards_list.yview)
        scrollbar.grid(row=3, column=1, sticky="ns")
        self.cards_list.configure(yscrollcommand=scrollbar.set)
        self.cards_list.bind("<Double-1>", self.record_card_payment)

        actions = tk.Frame(view, bg=theme["background"])
        actions.grid(row=4, column=0, columnspan=2, sticky="e", pady=(SPACE_3, 0))
        self.card_add_button = PillButton(
            actions, "Add card", self.open_add_card_dialog, theme, glyph=ICON_ADD
        )
        self.card_add_button.grid(row=0, column=0, padx=(0, SPACE_2))
        self.card_record_button = PillButton(
            actions, "Record payment", self.record_card_payment, theme,
            variant="tonal", glyph=ICON_PAID,
        )
        self.card_record_button.grid(row=0, column=1, padx=(0, SPACE_2))
        self.card_edit_button = PillButton(
            actions, "Edit", self.edit_selected_card, theme, variant="tonal", glyph=ICON_EDIT
        )
        self.card_edit_button.grid(row=0, column=2, padx=(0, SPACE_2))
        self.card_delete_button = PillButton(
            actions, "Delete", self.delete_selected_card, theme, variant="outlined", glyph=ICON_DELETE
        )
        self.card_delete_button.grid(row=0, column=3)
        self.themed_buttons.extend([
            self.card_add_button, self.card_record_button,
            self.card_edit_button, self.card_delete_button,
        ])

    def _draw_card_stats(self) -> None:
        """Three tiles above the card list, matching the dashboard's."""
        if not hasattr(self, "card_stats_canvas"):
            return
        theme = self._theme()
        canvas = self.card_stats_canvas
        canvas.configure(bg=theme["background"])
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)

        values = getattr(self, "card_stat_values", {"year": 0.0, "month": 0.0, "outstanding": 0})
        outstanding = values["outstanding"]
        tiles = [
            ("PAID ON CARDS IN " + str(self.current_date.year),
             "$" + format(values["year"], ",.2f"), theme["text"]),
            ("PAID THIS MONTH",
             "$" + format(values["month"], ",.2f"), theme["positive"]),
            ("STILL TO PAY",
             str(outstanding) + (" card" if outstanding == 1 else " cards"),
             theme["accent"] if outstanding else theme["text_secondary"]),
        ]

        gap = SPACE_3
        tile_width = (width - gap * (len(tiles) - 1) - 2) // len(tiles)
        top, bottom = 5, height - 7
        for index, (label, value, value_color) in enumerate(tiles):
            x1 = 1 + index * (tile_width + gap)
            x2 = x1 + tile_width
            draw_elevation(canvas, x1, top, x2, bottom, RADIUS_CARD, theme["background"], theme["shadow"], level=1)
            draw_rounded_rect(canvas, x1, top, x2, bottom, RADIUS_CARD, theme["surface"], theme["outline_variant"])
            canvas.create_text(
                x1 + SPACE_4, top + SPACE_4, text=label, anchor="nw",
                fill=theme["text_muted"], font=text_font(8, bold=True),
            )
            canvas.create_text(
                x1 + SPACE_4, top + SPACE_4 + 17, text=value, anchor="nw",
                fill=value_color, font=display_font(19),
            )

    def populate_cards_list(self) -> None:
        if not hasattr(self, "cards_list"):
            return
        for row_id in self.cards_list.get_children():
            self.cards_list.delete(row_id)

        year, month = self.current_date.year, self.current_date.month
        previous_year, previous_month = (year, month - 1) if month > 1 else (year - 1, 12)
        this_month = get_card_payments(self.data_file, year, month)
        last_month = get_card_payments(self.data_file, previous_year, previous_month)
        year_totals = get_card_year_totals(self.data_file, year)

        for card in self.cards:
            run_rate = subscription_run_rate_for_source(self.expenses, card.id)
            linked = len(expenses_charged_to(self.expenses, card.id))
            subs_text = "—" if not linked else (
                str(linked) + " · $" + format(run_rate, ",.2f") + "/mo"
            )

            if not card.is_card:
                # A bank account has no bill of its own, so every column about
                # paying one off is blank rather than zero. Zero would claim
                # something was owed and settled.
                self.cards_list.insert(
                    "", "end",
                    values=(card.name, KIND_LABELS[card.kind], "—", subs_text, "—", "—", "—", "—"),
                    iid=card.id,
                )
                continue

            due = card_due_date(card, year, month)
            paid = this_month.get(card.id)
            previous = last_month.get(card.id)

            # The comparison is the reason this view exists: is what I am
            # paying down going up or coming down?
            if paid is None:
                change = "—"
            elif previous is None:
                change = "first"
            else:
                difference = round(paid - previous, 2)
                if abs(difference) < 0.005:
                    change = "same"
                else:
                    sign = "+" if difference > 0 else "−"
                    change = sign + "$" + format(abs(difference), ",.2f")

            self.cards_list.insert(
                "", "end",
                values=(
                    card.name,
                    KIND_LABELS[card.kind],
                    due.strftime("%d %b") if due else "—",
                    subs_text,
                    "not yet" if paid is None else "$" + format(paid, ",.2f"),
                    "—" if previous is None else "$" + format(previous, ",.2f"),
                    change,
                    "$" + format(year_totals.get(card.id, 0.0), ",.2f"),
                ),
                iid=card.id,
            )

        if not self.cards:
            self.cards_summary.config(
                text="Nothing here yet. Add a card to watch its due date, or a bank account so a "
                "subscription can say where it is charged."
            )
            self.card_stat_values = {"year": 0.0, "month": 0.0, "outstanding": 0}
            self._draw_card_stats()
            return

        billable = cards_only(self.cards)
        outstanding = [card for card in billable if card.id not in this_month]
        word = "payment source" if len(self.cards) == 1 else "payment sources"
        summary = str(len(self.cards)) + " " + word
        if outstanding:
            summary += "  ·  still to pay this month: " + ", ".join(card.name for card in outstanding)
        else:
            summary += "  ·  all settled this month"
        self.cards_summary.config(text=summary)

        self.card_stat_values = {
            "year": round(sum(year_totals.values()), 2),
            "month": round(sum(this_month.values()), 2),
            "outstanding": len(outstanding),
        }
        self._draw_card_stats()

    def _selected_card(self):
        selection = self.cards_list.selection()
        if not selection:
            return None
        return next((card for card in self.cards if card.id == selection[0]), None)

    def open_add_card_dialog(self) -> None:
        self._open_card_dialog(None)

    def edit_selected_card(self, _event=None) -> None:
        card = self._selected_card()
        if card is None:
            messagebox.showinfo("Nothing selected", "Select a card in the list first.")
            return
        self._open_card_dialog(card)

    def _open_card_dialog(self, card) -> None:
        dialog = CardDialog(
            self.root, self.data_file, self.refresh_view,
            theme_mode=self.theme_mode.get(), card=card,
        )
        dialog.grab_set()
        self.root.wait_window(dialog)

    def delete_selected_card(self, _event=None) -> None:
        card = self._selected_card()
        if card is None:
            messagebox.showinfo("Nothing selected", "Select a card in the list first.")
            return
        confirmed = messagebox.askyesno(
            "Delete card",
            "Delete '" + card.name + "'?\n\nThis also removes every payment you recorded against it.",
        )
        if not confirmed:
            return
        delete_card(self.data_file, card.id)
        self.refresh_view()

    def record_card_payment(self, _event=None) -> None:
        """Open a card's whole year, which is the shape of the real task.

        Filling in what has already been paid this year is one dialog rather
        than twelve prompts, and it replaces a raw simpledialog that ignored
        the application's styling entirely.
        """
        card = self._selected_card()
        if card is None:
            messagebox.showinfo("Nothing selected", "Select a card in the list first.")
            return
        if not card.is_card:
            messagebox.showinfo(
                "Nothing to record",
                card.name + " is a bank account. Money leaves it when a subscription bills, so "
                "there is no separate payment to record.",
            )
            return

        dialog = CardPaymentDialog(
            self.root, self.data_file, self.refresh_view, card,
            self.current_date.year, theme_mode=self.theme_mode.get(),
        )
        dialog.grab_set()
        self.root.wait_window(dialog)

    # --- calendar -----------------------------------------------------
    def _build_calendar_view(self, theme: dict) -> None:
        view = self._new_view("calendar", theme)
        # The day list does not benefit from extra width, so it keeps a fixed
        # size and every spare pixel goes to the calendar, where it buys
        # readable subscription names instead of truncated ones.
        view.columnconfigure(0, weight=1)
        view.columnconfigure(1, weight=0, minsize=DETAILS_WIDTH)
        view.rowconfigure(1, weight=1)

        monthbar = tk.Frame(view, bg=theme["background"])
        monthbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, SPACE_3))
        monthbar.columnconfigure(2, weight=1)

        self.previous_button = IconButton(monthbar, ICON_CHEVRON_LEFT, self.previous_month, theme, variant="tonal")
        self.previous_button.grid(row=0, column=0)
        self.next_button = IconButton(monthbar, ICON_CHEVRON_RIGHT, self.next_month, theme, variant="tonal")
        self.next_button.grid(row=0, column=1, padx=(SPACE_2, SPACE_3))
        self.month_label = ttk.Label(monthbar, text="", font=display_font(16))
        self.month_label.grid(row=0, column=2, sticky="w")
        self.themed_buttons.extend([self.previous_button, self.next_button])

        self.calendar_frame = ttk.Frame(view)
        self.calendar_frame.grid(row=1, column=0, sticky="nsew", padx=(0, SPACE_5))
        for column_index in range(7):
            self.calendar_frame.columnconfigure(column_index, weight=1, uniform="calendar_columns")
        self.calendar_frame.rowconfigure(0, weight=0)
        for row_index in range(1, 7):
            self.calendar_frame.rowconfigure(row_index, weight=1, uniform="calendar_rows")

        # A stretchable Treeview column writes its stretched width back into the
        # column, which inflates the frame's requested width and steals space from
        # the calendar every time the layout is recalculated. Pinning the frame's
        # own size stops that feedback loop from reaching the parent grid.
        self.details_frame = ttk.Frame(view, width=DETAILS_WIDTH)
        self.details_frame.grid(row=1, column=1, sticky="nsew")
        self.details_frame.grid_propagate(False)
        self.details_frame.columnconfigure(0, weight=1)
        self.details_frame.rowconfigure(2, weight=1)

        self.selected_day_label = ttk.Label(self.details_frame, text="Selected day", style="Section.TLabel")
        self.selected_day_label.grid(row=0, column=0, columnspan=2, sticky="w")

        self.day_summary_canvas = tk.Canvas(
            self.details_frame, height=32, bg=theme["background"], highlightthickness=0
        )
        self.day_summary_canvas.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACE_2, SPACE_3))
        self.day_summary_canvas.bind("<Configure>", lambda _event: self._draw_day_summary_card())

        self.details_list = ttk.Treeview(
            self.details_frame,
            columns=("description", "amount", "status"),
            show="headings",
            height=12,
        )
        self.details_list.heading("description", text="DESCRIPTION", anchor="w")
        self.details_list.heading("amount", text="AMOUNT", anchor="e")
        self.details_list.heading("status", text="STATUS", anchor="center")
        # These must total less than DETAILS_WIDTH minus the scrollbar, or the
        # last column is clipped off the edge of the panel.
        self.details_list.column("description", width=192, minwidth=110, anchor="w", stretch=True)
        self.details_list.column("amount", width=72, minwidth=64, anchor="e", stretch=False)
        self.details_list.column("status", width=68, minwidth=60, anchor="center", stretch=False)
        self.details_list.grid(row=2, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self.details_frame, orient="vertical", command=self.details_list.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.details_list.configure(yscrollcommand=scrollbar.set)
        self.details_list.bind("<Delete>", self.delete_selected_entry)
        self.details_list.bind("<Double-1>", self.toggle_selected_paid)
        self.details_list.bind("<Button-3>", self.show_context_menu)

        actions = tk.Frame(self.details_frame, bg=theme["background"])
        actions.grid(row=3, column=0, columnspan=2, sticky="e", pady=(SPACE_3, 0))
        self.paid_button = PillButton(
            actions, "Mark paid", self.toggle_selected_paid, theme, variant="tonal", glyph=ICON_PAID
        )
        self.paid_button.grid(row=0, column=0, padx=(0, SPACE_2))
        self.edit_button = PillButton(
            actions, "Edit", self.edit_selected_entry, theme, variant="tonal", glyph=ICON_EDIT
        )
        self.edit_button.grid(row=0, column=1, padx=(0, SPACE_2))
        self.delete_button = PillButton(
            actions, "Delete", self.delete_selected_entry, theme, variant="outlined", glyph=ICON_DELETE
        )
        self.delete_button.grid(row=0, column=2)
        self.themed_buttons.extend([self.paid_button, self.edit_button, self.delete_button])

    # --- statistics ---------------------------------------------------
    def _build_statistics_view(self, theme: dict) -> None:
        view = self._new_view("statistics", theme)
        view.columnconfigure(0, weight=1)
        view.rowconfigure(1, weight=3)
        view.rowconfigure(2, weight=2)

        controls = tk.Frame(view, bg=theme["background"])
        controls.grid(row=0, column=0, sticky="ew", pady=(0, SPACE_3))
        controls.columnconfigure(1, weight=1)

        self.style_control = SegmentedControl(
            controls,
            (("donut", "Donut"), ("bars", "Bars")),
            self._set_chart_style,
            theme,
        )
        self.style_control.grid(row=0, column=0, sticky="w")
        self.themed_buttons.append(self.style_control)

        self.trend_canvas = tk.Canvas(view, bg=theme["background"], highlightthickness=0)
        self.trend_canvas.grid(row=1, column=0, sticky="nsew")
        self.trend_canvas.bind("<Configure>", lambda _event: self._draw_trend_chart())

        self.breakdown_canvas = tk.Canvas(view, bg=theme["background"], highlightthickness=0)
        self.breakdown_canvas.grid(row=2, column=0, sticky="nsew", pady=(SPACE_4, 0))
        self.breakdown_canvas.bind("<Configure>", lambda _event: self._draw_breakdown())


    # ------------------------------------------------------------------
    # Card drawing
    # ------------------------------------------------------------------

    def _draw_card(self, canvas: tk.Canvas, title: str, note: str = "") -> tuple:
        """Paint an elevated card filling the canvas; return its content box."""
        theme = self._theme()
        canvas.configure(bg=theme["background"])
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        if width < 40 or height < 40:
            return (0, 0, 0, 0)

        x1, y1, x2, y2 = 2, 2, width - 3, height - 4
        draw_elevation(canvas, x1, y1, x2, y2, RADIUS_CARD, theme["background"], theme["shadow"], level=1)
        draw_rounded_rect(canvas, x1, y1, x2, y2, RADIUS_CARD, theme["surface"], theme["outline_variant"])

        canvas.create_text(
            x1 + SPACE_4, y1 + SPACE_4, text=title, anchor="nw",
            fill=theme["text_muted"], font=text_font(8, bold=True),
        )
        if note:
            canvas.create_text(
                x2 - SPACE_4, y1 + SPACE_4, text=note, anchor="ne",
                fill=theme["text_muted"], font=text_font(8),
            )
        return (x1 + SPACE_4, y1 + SPACE_4 + 22, x2 - SPACE_4, y2 - SPACE_3)

    def _draw_brand(self) -> None:
        """The wordmark: a ruled ledger mark, then Due in ink and Khata in accent.

        Splitting the two halves by colour is what makes the name read as one
        word rather than two, and it carries the meaning: what is due, and the
        ledger it is written in.
        """
        if not hasattr(self, "brand_canvas"):
            return
        theme = self._theme()
        canvas = self.brand_canvas
        canvas.configure(bg=theme["surface_1"])
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)

        # A small ledger: three ruled entries, each shorter than the last.
        badge = 34
        badge_x, badge_y = SPACE_3, 15
        draw_rounded_rect(
            canvas, badge_x, badge_y, badge_x + badge, badge_y + badge, 11, theme["accent"]
        )
        for index, line_width in enumerate((17, 13, 9)):
            line_y = badge_y + 11 + index * 6
            canvas.create_rectangle(
                badge_x + 9, line_y, badge_x + 9 + line_width, line_y + 2,
                fill=theme["on_accent"], outline="",
            )

        wordmark_font = display_font(17)
        measure = tkfont.Font(self.root, font=wordmark_font)
        text_x = badge_x + badge + 11
        baseline = badge_y + 13

        canvas.create_text(
            text_x, baseline, text="Due", anchor="w", fill=theme["text"], font=wordmark_font
        )
        canvas.create_text(
            text_x + measure.measure("Due"), baseline, text="Khata", anchor="w",
            fill=theme["accent"], font=wordmark_font,
        )
        canvas.create_text(
            text_x + 1, badge_y + 30, text="v" + APP_VERSION, anchor="w",
            fill=theme["text_muted"], font=text_font(8),
        )

        canvas.create_line(
            SPACE_3, 66, max(width - SPACE_3, SPACE_3), 66, fill=theme["outline_variant"]
        )

    def _draw_user(self) -> None:
        """Who is signed in, sitting at the foot of the rail."""
        if not hasattr(self, "user_canvas"):
            return
        theme = self._theme()
        canvas = self.user_canvas
        canvas.configure(bg=theme["surface_1"])
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)

        initial = (self.authenticated_username or "?").strip()[:1].upper()
        size = 26
        top = 4
        canvas.create_oval(
            0, top, size, top + size, fill=theme["accent_soft"], outline=theme["accent"]
        )
        canvas.create_text(
            size // 2, top + size // 2, text=initial, fill=theme["accent"], font=text_font(10, bold=True)
        )
        canvas.create_text(
            size + 9, top + size // 2, text=self._display_name(), anchor="w",
            fill=theme["text_secondary"], font=text_font(9, bold=True), width=max(20, width - size - 12),
        )

    def _draw_category_chart(self) -> None:
        if not hasattr(self, "category_canvas"):
            return
        month_name = self.current_date.strftime("%B")
        box = self._draw_card(self.category_canvas, "SPEND BY CATEGORY", month_name.upper())
        if box == (0, 0, 0, 0):
            return
        theme = self._theme()
        left, top, right, bottom = box
        canvas = self.category_canvas

        rows = get_category_totals(
            self.expenses, self.current_date.year, self.current_date.month
        )
        if not rows:
            canvas.create_text(
                left, top + 8, text="Nothing due this month.", anchor="nw",
                fill=theme["text_muted"], font=text_font(10),
            )
            return

        largest = max(value for _name, value in rows) or 1.0
        row_height = 34
        visible = max(1, min(len(rows), int((bottom - top) // row_height)))
        palette = CATEGORY_COLOURS

        for index, (name, value) in enumerate(rows[:visible]):
            y = top + 6 + index * row_height
            colour = palette[index % len(palette)]
            canvas.create_text(
                left, y, text=name, anchor="nw", fill=theme["text"], font=text_font(9, bold=True)
            )
            canvas.create_text(
                right, y, text=f"${value:,.2f}", anchor="ne",
                fill=theme["text_secondary"], font=text_font(9),
            )
            track_top = y + 18
            draw_rounded_rect(canvas, left, track_top, right, track_top + 7, 3, theme["surface_2"])
            span = max(6, int((right - left) * (value / largest)))
            draw_rounded_rect(canvas, left, track_top, left + span, track_top + 7, 3, colour)

        if len(rows) > visible:
            canvas.create_text(
                left, bottom - 4, text=f"+{len(rows) - visible} more", anchor="sw",
                fill=theme["text_muted"], font=text_font(8),
            )

    def _draw_upcoming(self) -> None:
        if not hasattr(self, "upcoming_canvas"):
            return
        box = self._draw_card(self.upcoming_canvas, "COMING UP", "NEXT 14 DAYS")
        if box == (0, 0, 0, 0):
            return
        theme = self._theme()
        left, top, right, bottom = box
        canvas = self.upcoming_canvas

        today = date.today()
        # Card due dates belong here: this panel answers "what is coming?", which
        # is a question about dates. It is not a total, so nothing is miscounted.
        entries = [(day, expense, False) for day, expense in get_upcoming(self.expenses, today, days=14)]
        entries += [(day, card, True) for day, card in get_cards_due_between(self.cards, today, days=14)]
        entries.sort(key=lambda row: (row[0], row[1].name.lower() if row[2] else row[1].description.lower()))
        if not entries:
            canvas.create_text(
                left, top + 8, text="Nothing due in the next two weeks.", anchor="nw",
                fill=theme["text_muted"], font=text_font(10),
            )
            return

        row_height = 30
        visible = max(1, min(len(entries), int((bottom - top) // row_height)))
        for index, (day, entry, is_card) in enumerate(entries[:visible]):
            y = top + 6 + index * row_height
            delta = (day - today).days
            if delta == 0:
                when, when_colour = "Today", theme["accent"]
            elif delta == 1:
                when, when_colour = "Tomorrow", theme["text_secondary"]
            else:
                when, when_colour = day.strftime("%a %d %b"), theme["text_secondary"]

            colour = entry.color or theme["accent"]
            canvas.create_rectangle(left, y + 2, left + 3, y + 17, fill=colour, outline="")
            canvas.create_text(
                left + 10, y, text=entry.name if is_card else entry.description, anchor="nw",
                fill=theme["text"], font=text_font(9, bold=True),
            )
            canvas.create_text(
                left + 10, y + 14, text=when, anchor="nw", fill=when_colour, font=text_font(8)
            )
            if is_card:
                # No amount: what a card costs is not known until it is paid.
                canvas.create_text(
                    right, y + 5, text="card", anchor="ne",
                    fill=theme["text_muted"], font=text_font(8),
                )
            elif entry.amount is not None:
                canvas.create_text(
                    right, y + 5, text=f"${entry.amount:,.2f}", anchor="ne",
                    fill=theme["text"], font=text_font(9),
                )

        if len(entries) > visible:
            canvas.create_text(
                left, bottom - 4, text=f"+{len(entries) - visible} more", anchor="sw",
                fill=theme["text_muted"], font=text_font(8),
            )

    def _draw_trend_chart(self, canvas: tk.Canvas | None = None) -> None:
        canvas = canvas if canvas is not None else getattr(self, "trend_canvas", None)
        if canvas is None:
            return
        year = self.current_date.year
        box = self._draw_card(canvas, "MONTHLY SPEND", str(year))
        if box == (0, 0, 0, 0):
            return
        theme = self._theme()
        left, top, right, bottom = box

        totals = get_monthly_totals(self.expenses, year)
        largest = max(totals) or 1.0
        baseline = bottom - 20
        usable = max(20, baseline - top - 28)
        slot = (right - left) / 12.0
        bar_width = max(8, int(slot * 0.52))

        for index, value in enumerate(totals):
            centre = left + slot * (index + 0.5)
            height = int(usable * (value / largest)) if value else 0
            x1 = int(centre - bar_width / 2)
            x2 = int(centre + bar_width / 2)
            is_current = (index + 1) == self.current_date.month
            colour = theme["accent"] if is_current else mix(theme["surface"], theme["accent"], 0.34)
            if height > 0:
                draw_rounded_rect(canvas, x1, baseline - height, x2, baseline, 4, colour)
            else:
                canvas.create_line(x1, baseline - 1, x2, baseline - 1, fill=theme["outline"])

            canvas.create_text(
                centre, baseline + 6, text=calendar.month_abbr[index + 1][:1],
                anchor="n", fill=theme["accent"] if is_current else theme["text_muted"],
                font=text_font(8, bold=is_current),
            )
            if is_current and value:
                canvas.create_text(
                    centre, baseline - height - 4, text=f"${value:,.0f}", anchor="s",
                    fill=theme["text"], font=text_font(8, bold=True),
                )

    def _draw_breakdown(self) -> None:
        """Share of the year's spending, as a donut or as ranked bars."""
        if not hasattr(self, "breakdown_canvas"):
            return
        year = self.current_date.year
        heading = "SHARE BY CATEGORY"
        box = self._draw_card(self.breakdown_canvas, heading, f"{year} TOTAL")
        if box == (0, 0, 0, 0):
            return
        theme = self._theme()
        left, top, right, bottom = box
        canvas = self.breakdown_canvas

        yearly: dict = {}
        for month in range(1, 13):
            for name, value in get_totals_by(self.expenses, year, month):
                yearly[name] = yearly.get(name, 0.0) + value
        rows = sorted(yearly.items(), key=lambda item: -item[1])
        total = sum(value for _name, value in rows)

        if not rows or total <= 0:
            canvas.create_text(
                left, top + 8, text="No spending recorded for this year yet.", anchor="nw",
                fill=theme["text_muted"], font=text_font(10),
            )
            return

        if self.chart_style == "donut":
            self._draw_donut(canvas, rows, total, left, top, right, bottom)
        else:
            self._draw_ranked_bars(canvas, rows, total, left, top, right, bottom)

    def _draw_donut(self, canvas, rows, total, left, top, right, bottom) -> None:
        theme = self._theme()
        size = max(80, min(bottom - top - 8, 224))
        cx = left + size // 2
        cy = top + (bottom - top) // 2
        radius = size // 2

        start = 90.0
        for index, (_name, value) in enumerate(rows):
            extent = -(value / total) * 360.0
            if abs(extent) < 0.2:
                continue
            canvas.create_arc(
                cx - radius, cy - radius, cx + radius, cy + radius,
                start=start, extent=extent, style="pieslice",
                fill=CATEGORY_COLOURS[index % len(CATEGORY_COLOURS)], outline=theme["surface"],
            )
            start += extent

        # The hole is what makes it a donut, and gives the total somewhere to live.
        hole = int(radius * 0.58)
        canvas.create_oval(cx - hole, cy - hole, cx + hole, cy + hole, fill=theme["surface"], outline="")
        canvas.create_text(cx, cy - 8, text=f"${total:,.0f}", fill=theme["text"], font=display_font(15))
        canvas.create_text(cx, cy + 10, text="THIS YEAR", fill=theme["text_muted"], font=text_font(7, bold=True))

        # Keep the legend as one block beside the donut. Pinning the figures to
        # the card edge instead leaves a gulf of empty space on a wide window.
        legend_x = cx + radius + SPACE_6
        legend_right = min(right, legend_x + 300)
        for index, (name, value) in enumerate(rows[:8]):
            y = top + 6 + index * 21
            if y > bottom - 12:
                break
            canvas.create_rectangle(
                legend_x, y + 3, legend_x + 9, y + 12,
                fill=CATEGORY_COLOURS[index % len(CATEGORY_COLOURS)], outline="",
            )
            canvas.create_text(
                legend_x + 16, y, text=name, anchor="nw",
                fill=theme["text_secondary"], font=text_font(9),
            )
            canvas.create_text(
                legend_right, y, text=f"{value / total * 100:.0f}%   ${value:,.0f}", anchor="ne",
                fill=theme["text"], font=text_font(9),
            )

    def _draw_ranked_bars(self, canvas, rows, total, left, top, right, bottom) -> None:
        theme = self._theme()
        largest = max(value for _name, value in rows) or 1.0
        row_height = 34
        visible = max(1, min(len(rows), int((bottom - top) // row_height)))

        for index, (name, value) in enumerate(rows[:visible]):
            y = top + 6 + index * row_height
            colour = CATEGORY_COLOURS[index % len(CATEGORY_COLOURS)]
            canvas.create_text(
                left, y, text=name, anchor="nw", fill=theme["text"], font=text_font(9, bold=True)
            )
            canvas.create_text(
                right, y, text=f"{value / total * 100:.0f}%   ${value:,.2f}", anchor="ne",
                fill=theme["text_secondary"], font=text_font(9),
            )
            track_top = y + 18
            draw_rounded_rect(canvas, left, track_top, right, track_top + 7, 3, theme["surface_2"])
            span = max(6, int((right - left) * (value / largest)))
            draw_rounded_rect(canvas, left, track_top, left + span, track_top + 7, 3, colour)

        if len(rows) > visible:
            canvas.create_text(
                left, bottom - 4, text=f"+{len(rows) - visible} more", anchor="sw",
                fill=theme["text_muted"], font=text_font(8),
            )


    def _available_categories(self) -> list[str]:
        return sorted({expense.category for expense in self.expenses if expense.category})

    def _set_chart_style(self, style: str) -> None:
        self.chart_style = style
        self._draw_breakdown()

    def _format_total_rows(self, projected: float, remaining: float) -> tuple[str, str]:
        return (
            f"Projected monthly total: ${projected:.2f}",
            f"Remaining this month: ${remaining:.2f}",
        )

    def _wrap_calendar_text(self, text: str, max_width: int, max_lines: int = 2) -> list[str]:
        if not text:
            return [""]

        tokens = text.split()
        lines: list[str] = []
        current = ""
        for token in tokens:
            if not token:
                continue
            candidate = f"{current} {token}".strip()
            if self.calendar_font.measure(candidate) <= max_width:
                current = candidate
                continue

            if current:
                lines.append(current)
            else:
                split_token = ""
                for ch in token:
                    if self.calendar_font.measure(split_token + ch) <= max_width:
                        split_token += ch
                    else:
                        break
                if not split_token:
                    split_token = token[:1]
                lines.append(split_token)
            current = ""
            if len(lines) >= max_lines:
                break

        if current and len(lines) < max_lines:
            lines.append(current)

        if lines and len(lines) == max_lines:
            line_end = token if tokens else ""
            if line_end and line_end not in lines[-1]:
                lines[-1] = (lines[-1].rstrip(" .") + "...") if not lines[-1].endswith("...") else lines[-1]

        return lines[:max_lines]

    def refresh_view(self) -> None:
        self.expenses = load_expenses(self.data_file)
        self.cards = load_cards(self.data_file)
        self.paid_expense_ids = get_paid_expense_ids(self.data_file, self.current_date.year, self.current_date.month)
        self._refresh_theme_button()

        self.month_label.config(text=self.current_date.strftime("%B %Y"))

        projected_total = get_total_for_month(self.expenses, self.current_date.year, self.current_date.month)
        paid_total = get_paid_total_for_month(
            self.expenses,
            self.paid_expense_ids,
            self.current_date.year,
            self.current_date.month,
        )
        remaining_total = round(projected_total - paid_total, 2)
        self.stat_values = {
            "projected": projected_total,
            "remaining": remaining_total,
            "paid": paid_total,
            "yearly": get_yearly_total(self.expenses, self.current_date.year),
            "run_rate": get_monthly_run_rate(self.expenses),
        }
        # A month carrying yearly or one-off billing is genuinely higher than a
        # normal month. Saying so where the number appears saves the reader
        # wondering whether the total is wrong.
        self.irregular_this_month = get_irregular_total_for_month(
            self.expenses, self.current_date.year, self.current_date.month
        )

        day_expenses = get_expenses_for_day(self.expenses, self.selected_date)
        day_total = sum(expense.amount or 0 for expense in day_expenses)
        day_paid = sum(expense.amount or 0 for expense in day_expenses if expense.id in self.paid_expense_ids)
        entry_word = "subscription" if len(day_expenses) == 1 else "subscriptions"
        self.day_summary_text = (
            f"{len(day_expenses)} {entry_word}  ·  ${day_total:,.2f} due  ·  ${day_paid:,.2f} paid"
        )
        self.selected_day_label.config(text=self.selected_date.strftime("%A, %B %d"))
        self.subtitle_label.config(text=self._welcome_text())
        self._apply_color_pallets()

        self._draw_brand()
        self._draw_user()
        self._draw_stat_cards()
        self._draw_category_chart()
        self._draw_upcoming()
        self._draw_trend_chart()
        if hasattr(self, "dash_trend_canvas"):
            self._draw_trend_chart(self.dash_trend_canvas)
        self._draw_breakdown()
        self._draw_day_summary_card()

        self.populate_all_list()
        self.populate_cards_list()
        self.populate_calendar()
        self.populate_details()

    def _apply_color_pallets(self) -> None:
        """Repaint plain container frames after a theme change.

        The sidebar sits on a raised surface rather than the page background, so
        its subtree is skipped; repainting it would flatten the rail into the
        rest of the window.
        """
        theme = self._theme()
        self.root.configure(bg=theme["background"])
        sidebar = getattr(self, "sidebar", None)

        def recolor_containers(widget, background) -> None:
            for child in widget.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=background)
                recolor_containers(child, background)

        if sidebar is not None:
            sidebar.configure(bg=theme["surface_1"])
            recolor_containers(sidebar, theme["surface_1"])
            for item in self.nav_items.values():
                item.set_theme(theme, theme["surface_1"])
            if hasattr(self, "theme_button"):
                self.theme_button.set_theme(theme, theme["surface_1"])

        for child in self.root.winfo_children():
            if child is sidebar:
                continue
            if isinstance(child, tk.Frame):
                child.configure(bg=theme["background"])
            recolor_containers(child, theme["background"])

        for label, foreground_key in getattr(self, "themed_labels", []):
            label.configure(bg=theme["background"], fg=theme[foreground_key])

    def _render_calendar_cell(
        self,
        cell: tk.Canvas,
        current_day: date | None,
        items: list,
        is_selected: bool = False,
        is_today: bool = False,
        cards: list | None = None,
    ) -> None:
        theme = self._theme()
        cell.delete("all")
        width = max(cell.winfo_width(), 72)
        height = max(cell.winfo_height(), 72)
        is_dark = self.theme_mode.get() == "dark"

        if current_day is None:
            # Days from the neighbouring month stay flat and unlabelled.
            draw_rounded_rect(cell, 2, 2, width - 3, height - 3, RADIUS_CARD, theme["calendar_outside"])
            return

        if is_selected:
            bg_color = theme["calendar_selected"]
            outline_color = theme["calendar_selected_border"]
            outline_width = 2
        elif is_today:
            bg_color = theme["calendar_today"]
            outline_color = theme["calendar_today_border"]
            outline_width = 1
        else:
            bg_color = theme["calendar_cell"]
            outline_color = theme["outline_variant"]
            outline_width = 1

        draw_elevation(cell, 3, 3, width - 4, height - 5, RADIUS_CARD, theme["calendar_bg"], theme["shadow"], level=1)
        draw_rounded_rect(cell, 3, 3, width - 4, height - 5, RADIUS_CARD, bg_color, outline_color, width=outline_width)

        # Today's date sits inside a filled accent disc, as on Android.
        day_text = str(current_day.day)
        if is_today:
            disc_radius = 11
            centre_x, centre_y = SPACE_3 + disc_radius - 3, SPACE_3 + disc_radius - 4
            cell.create_oval(
                centre_x - disc_radius,
                centre_y - disc_radius,
                centre_x + disc_radius,
                centre_y + disc_radius,
                fill=theme["accent"],
                outline="",
            )
            cell.create_text(centre_x, centre_y, text=day_text, fill=theme["on_accent"], font=text_font(10, bold=True))
        else:
            cell.create_text(SPACE_3, SPACE_2 + 1, text=day_text, anchor="nw", fill=theme["text"], font=text_font(10, bold=True))

        cards = cards or []
        if not items and not cards:
            return

        # A day cell is barely 100px wide, so the chips carry the names and the
        # day's total is summarised once in the header instead of per chip.
        # Cards are excluded: what they settle is already counted below.
        day_total = sum(expense.amount or 0 for expense in items)
        if day_total:
            cell.create_text(
                width - SPACE_3,
                SPACE_2 + 2,
                text=f"${day_total:,.0f}",
                anchor="ne",
                fill=theme["text_secondary"],
                font=text_font(9, bold=True),
            )

        chip_height = 18
        chip_gap = 3
        top = SPACE_2 + 22
        available = height - top - SPACE_2 - 6
        capacity = max(1, available // (chip_height + chip_gap))
        total_entries = len(items) + len(cards)
        # One slot is surrendered to the "+N more" line when not everything fits.
        slots = capacity if total_entries <= capacity else max(1, capacity - 1)

        chip_font = text_font(8)
        left = SPACE_2
        right = width - SPACE_2 - 4
        y = top

        # Cards are drawn first so a due date is never the thing hidden behind
        # "+2 more", and hollow so they read as an obligation rather than a
        # purchase.
        visible_cards = cards[:slots]
        visible_items = items[:slots - len(visible_cards)]

        for card in visible_cards:
            accent_color = card.color or theme["accent"]
            draw_chip(
                cell,
                left,
                y,
                right,
                y + chip_height,
                bg_color,
                accent_color,
                self._truncate_to_width(card.name, max(18, right - left - 16)),
                theme["text_secondary"],
                chip_font,
            )
            draw_rounded_rect(
                cell, left, y, right, y + chip_height, min(RADIUS_CHIP, chip_height // 2),
                "", mix(accent_color, theme["surface"], 0.25), width=1,
            )
            y += chip_height + chip_gap

        for expense in visible_items:
            accent_color = expense.color or theme["accent"]
            is_paid = expense.id in self.paid_expense_ids
            tint = 0.30 if is_dark else 0.42
            chip_fill = mix(bg_color, accent_color, tint * (0.45 if is_paid else 1.0))
            label_color = theme["text_muted"] if is_paid else theme["text"]

            prefix = f"{icon(ICON_PAID)} " if is_paid else ""
            label = self._truncate_to_width(
                prefix + expense.description,
                max(18, right - left - 16),
            )

            draw_chip(
                cell,
                left,
                y,
                right,
                y + chip_height,
                chip_fill,
                mix(accent_color, theme["surface"], 0.4) if is_paid else accent_color,
                label,
                label_color,
                chip_font,
            )
            y += chip_height + chip_gap

        shown = len(visible_cards) + len(visible_items)
        if total_entries > shown:
            more_tag = f"calendar_more_{current_day.isoformat()}"
            remaining = total_entries - shown
            cell.create_text(
                left + 4,
                min(y + chip_height // 2, height - 14),
                text=f"+{remaining} more",
                anchor="w",
                fill=theme["accent"],
                font=text_font(8, bold=True),
                tags=(more_tag,),
            )
            cell.tag_bind(
                more_tag,
                "<Button-1>",
                lambda _event, clicked_items=tuple(items), clicked_day=current_day: self.open_day_expenses_popup(clicked_day, list(clicked_items)),
            )
            cell.tag_bind(more_tag, "<Enter>", lambda _event, target=cell: target.configure(cursor="hand2"))
            cell.tag_bind(more_tag, "<Leave>", lambda _event, target=cell: target.configure(cursor=""))

    def _truncate_to_width(self, text: str, max_width: int) -> str:
        if self.calendar_font.measure(text) <= max_width:
            return text
        ellipsis = "…"
        trimmed = text
        while trimmed and self.calendar_font.measure(trimmed + ellipsis) > max_width:
            trimmed = trimmed[:-1]
        return (trimmed.rstrip() + ellipsis) if trimmed else ellipsis

    def populate_calendar(self) -> None:
        theme = self._theme()
        for child in self.calendar_frame.winfo_children():
            child.destroy()

        day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        for index, day_name in enumerate(day_names):
            label = tk.Label(
                self.calendar_frame,
                text=day_name,
                bg=theme["background"],
                fg=theme["text_muted"],
                font=text_font(8, bold=True),
            )
            label.grid(row=0, column=index, sticky="ew", padx=SPACE_1, pady=(0, SPACE_2))

        month_calendar = calendar.monthcalendar(self.current_date.year, self.current_date.month)
        day_map = get_expenses_by_day(self.expenses, self.current_date.year, self.current_date.month)
        card_map = get_cards_due_in_month(self.cards, self.current_date.year, self.current_date.month)
        today = date.today()
        row = 1
        for week in month_calendar:
            for col, day in enumerate(week):
                if day == 0:
                    cell = tk.Canvas(self.calendar_frame, width=70, height=86, bg=theme["calendar_bg"], highlightthickness=0)
                    cell.grid(row=row, column=col, sticky="nsew", padx=SPACE_1, pady=SPACE_1)
                    cell.bind("<Configure>", lambda _event, target=cell: self._render_calendar_cell(target, None, []))
                    continue

                current_day = date(self.current_date.year, self.current_date.month, day)
                is_selected = current_day == self.selected_date
                is_today = current_day == today
                items = day_map.get(current_day.strftime("%Y-%m-%d"), [])
                day_cards = card_map.get(current_day.strftime("%Y-%m-%d"), [])
                cell = tk.Canvas(self.calendar_frame, width=70, height=86, bg=theme["calendar_bg"], highlightthickness=0)
                cell.grid(row=row, column=col, sticky="nsew", padx=SPACE_1, pady=SPACE_1)
                cell.bind(
                    "<Configure>",
                    lambda _event, target=cell, clicked_day=current_day, clicked_items=tuple(items), selected=is_selected, today_cell=is_today, clicked_cards=tuple(day_cards): self._render_calendar_cell(
                        target,
                        clicked_day,
                        list(clicked_items),
                        selected,
                        today_cell,
                        list(clicked_cards),
                    ),
                )

                cell.bind("<Button-1>", lambda _event, clicked_day=current_day: self.select_day(clicked_day))
            row += 1

    def open_day_expenses_popup(self, selected_day: date, expenses: list) -> None:
        popup = tk.Toplevel(self.root)
        popup.title(selected_day.strftime("%A, %b %d"))
        popup.configure(bg=self._theme()["background"])
        popup.transient(self.root)
        popup.grab_set()
        popup_width = min(720, max(620, self.root.winfo_width() - 120))
        popup_height = min(500, max(420, self.root.winfo_height() - 160))
        popup_x = max(20, self.root.winfo_rootx() + (self.root.winfo_width() - popup_width) // 2)
        popup_y = max(20, self.root.winfo_rooty() + (self.root.winfo_height() - popup_height) // 2)
        popup.geometry(f"{popup_width}x{popup_height}+{popup_x}+{popup_y}")
        popup.minsize(620, 400)

        content = ttk.Frame(popup, padding=12)
        content.pack(fill="both", expand=True)

        ttk.Label(
            content,
            text=f"{selected_day.strftime('%B %d, %Y')}",
            font=display_font(15),
        ).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(content)
        list_frame.pack(fill="both", expand=True)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        detail_list = ttk.Treeview(
            list_frame,
            columns=("description", "amount", "status"),
            show="headings",
            height=12,
        )
        detail_list.heading("description", text="Description")
        detail_list.heading("amount", text="Amount")
        detail_list.heading("status", text="Status")
        detail_list.column("description", width=410, minwidth=180, anchor="w", stretch=True)
        detail_list.column("amount", width=90, minwidth=80, anchor="e", stretch=False)
        detail_list.column("status", width=90, minwidth=80, anchor="center", stretch=False)
        detail_list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=detail_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        detail_list.configure(yscrollcommand=scrollbar.set)

        for expense in expenses:
            amount_text = "Planned" if expense.amount is None else f"${expense.amount:.2f}"
            status_text = "Paid" if expense.id in self.paid_expense_ids else "Pending"
            detail_list.insert(
                "", "end",
                values=(self._describe(expense), amount_text, status_text),
                iid=expense.id,
            )

        button_row = ttk.Frame(content)
        button_row.pack(fill="x", anchor="e", pady=(8, 0))
        ttk.Button(button_row, text="Close", command=popup.destroy).pack(side="right")
        popup.bind("<Escape>", lambda _event: popup.destroy())

    def _describe(self, expense) -> str:
        """Name plus anything that is not obvious from the calendar position."""
        parts = []
        if expense.cadence != CADENCE_MONTHLY:
            parts.append(CADENCE_LABELS[expense.cadence].lower())
        if expense.ends_on:
            parts.append(f"until {expense.ends_on}")
        if expense.amount is None and expense.due_day is not None:
            parts.append(f"due {expense.due_day}")
        return f"{expense.description}  ({', '.join(parts)})" if parts else expense.description

    def populate_details(self) -> None:
        for row_id in self.details_list.get_children():
            self.details_list.delete(row_id)

        expenses = get_expenses_for_day(self.expenses, self.selected_date)
        theme = self._theme()

        for card in self.cards:
            if card_due_date(card, self.selected_date.year, self.selected_date.month) != self.selected_date:
                continue
            self.details_list.insert(
                "", "end",
                values=(card.name, "—", "Card due"),
                iid=CARD_ROW_PREFIX + card.id,
            )

        for index, expense in enumerate(expenses):
            amount_text = "Planned" if expense.amount is None else f"${expense.amount:.2f}"
            status_text = "Paid" if expense.id in self.paid_expense_ids else "Pending"
            description = self._describe(expense)

            self.details_list.insert(
                "",
                "end",
                values=(description, amount_text, status_text),
                iid=expense.id,
            )
            if index % 2 == 1:
                self.details_list.item(expense.id, tags=("odd",))
        self.details_list.tag_configure("odd", background=theme["list_row_alt"])

    def select_day(self, selected_day: date) -> None:
        self.selected_date = selected_day
        self.refresh_view()

    def show_context_menu(self, event) -> None:
        selected = self.details_list.identify_row(event.y)
        if selected:
            self.details_list.selection_set(selected)
        else:
            self.details_list.selection_clear()

        selected_items = self.details_list.selection()
        if not selected_items:
            return

        expense_id = selected_items[0]
        expense_paid = expense_id in self.paid_expense_ids
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Mark as paid" if not expense_paid else "Mark as pending", command=self.toggle_selected_paid)
        menu.add_command(label="Edit subscription…", command=self.edit_selected_entry)
        menu.add_separator()
        menu.add_command(label="Delete", command=self.delete_selected_entry)
        menu.post(event.x_root, event.y_root)

    def toggle_selected_paid(self, _event=None) -> None:
        selected_items = self.details_list.selection()
        if not selected_items or self._reject_card_row(selected_items[0]):
            return
        expense_id = selected_items[0]
        is_paid = expense_id in self.paid_expense_ids
        set_expense_paid(self.data_file, expense_id, self.current_date.year, self.current_date.month, not is_paid)
        self.refresh_view()

    def delete_selected_entry(self, _event=None) -> None:
        selected_items = self.details_list.selection()
        if not selected_items or self._reject_card_row(selected_items[0]):
            return
        expense_id = selected_items[0]
        expense = next((item for item in self.expenses if item.id == expense_id), None)
        if expense is None:
            return
        confirmed = messagebox.askyesno("Delete expense", f"Delete '{expense.description}'?")
        if not confirmed:
            return

        delete_expense(self.data_file, expense_id)
        self.refresh_view()

    def previous_month(self) -> None:
        if self.current_date.month == 1:
            self.current_date = self.current_date.replace(year=self.current_date.year - 1, month=12)
        else:
            self.current_date = self.current_date.replace(month=self.current_date.month - 1)
        self.selected_date = self.current_date.replace(day=1)
        self.refresh_view()

    def next_month(self) -> None:
        if self.current_date.month == 12:
            self.current_date = self.current_date.replace(year=self.current_date.year + 1, month=1)
        else:
            self.current_date = self.current_date.replace(month=self.current_date.month + 1)
        self.selected_date = self.current_date.replace(day=1)
        self.refresh_view()

    def open_add_dialog(self) -> None:
        dialog = AddExpenseDialog(
            self.root,
            self.data_file,
            self.refresh_view,
            self.selected_date,
            self.expenses,
            theme_mode=self.theme_mode.get(),
            payment_sources=self.cards,
        )
        dialog.grab_set()
        self.root.wait_window(dialog)

    # --- the Subscriptions view ---------------------------------------

    CADENCE_LABELS = {
        CADENCE_ONCE: "Once",
        CADENCE_WEEKLY: "Weekly",
        CADENCE_MONTHLY: "Monthly",
        CADENCE_QUARTERLY: "Quarterly",
        CADENCE_YEARLY: "Yearly",
    }

    def populate_all_list(self) -> None:
        """Every subscription, regardless of month, newest billing date first."""
        if not hasattr(self, "all_list"):
            return
        for row_id in self.all_list.get_children():
            self.all_list.delete(row_id)

        search = self.search_var.get().strip().lower()
        wanted_category = self.category_filter.get()
        wanted_cadence = self.cadence_filter.get()
        today = date.today()

        self.category_box["values"] = (ALL_CATEGORIES,) + tuple(self._available_categories())
        if wanted_category not in self.category_box["values"]:
            wanted_category = ALL_CATEGORIES
            self.category_filter.set(wanted_category)

        rows = []
        for expense in self.expenses:
            if wanted_category != ALL_CATEGORIES and expense.category != wanted_category:
                continue
            if wanted_cadence != ALL_CADENCES:
                label = self.CADENCE_LABELS.get(expense.cadence, expense.cadence.title())
                if label != wanted_cadence:
                    continue
            if search and search not in expense.description.lower() and search not in expense.category.lower():
                continue
            following = next_occurrence(expense, today)
            rows.append((following, expense))

        # Anything still running sorts first, by how soon it is due; finished
        # subscriptions fall to the bottom in alphabetical order.
        rows.sort(key=lambda pair: (pair[0] is None, pair[0] or date.max, pair[1].description.lower()))

        for following, expense in rows:
            amount = "Planned" if expense.amount is None else f"${expense.amount:,.2f}"
            cadence = self.CADENCE_LABELS.get(expense.cadence, expense.cadence.title())
            if following is None:
                due = "Ended"
            elif following == today:
                due = "Today"
            else:
                due = following.strftime("%d %b %Y")
            self.all_list.insert(
                "",
                "end",
                iid=expense.id,
                values=(
                    expense.description, amount, cadence, due, expense.category,
                    payment_source_name(self.cards, expense.paid_with) or "—",
                ),
            )

        total = len([e for e in self.expenses if e.amount is not None])
        shown = len(rows)
        if hasattr(self, "result_label"):
            word = "subscription" if shown == 1 else "subscriptions"
            if shown == len(self.expenses):
                self.result_label.config(text=f"{shown} {word}")
            else:
                self.result_label.config(text=f"{shown} of {len(self.expenses)} {word}")

    def _selected_from_all_list(self):
        selection = self.all_list.selection()
        if not selection:
            return None
        return next((item for item in self.expenses if item.id == selection[0]), None)

    def edit_from_all_list(self, _event=None) -> None:
        expense = self._selected_from_all_list()
        if expense is None:
            messagebox.showinfo("Nothing selected", "Select a subscription in the list first.")
            return
        self._open_edit_dialog(expense)

    def delete_from_all_list(self, _event=None) -> None:
        expense = self._selected_from_all_list()
        if expense is None:
            messagebox.showinfo("Nothing selected", "Select a subscription in the list first.")
            return
        confirmed = messagebox.askyesno(
            "Delete subscription",
            f"Delete '{expense.description}'?\n\nThis also removes every month you marked it paid.",
        )
        if not confirmed:
            return
        delete_expense(self.data_file, expense.id)
        self.refresh_view()

    def _reject_card_row(self, row_id: str) -> bool:
        """Card rows appear in the day list but are not editable from it."""
        if not row_id.startswith(CARD_ROW_PREFIX):
            return False
        messagebox.showinfo(
            "That is a card",
            "Card due dates are managed in the Cards view, not here.",
        )
        return True

    def _selected_expense(self):
        selection = self.details_list.selection()
        if not selection:
            return None
        return next((item for item in self.expenses if item.id == selection[0]), None)

    def edit_selected_entry(self, _event=None) -> None:
        selection = self.details_list.selection()
        if selection and self._reject_card_row(selection[0]):
            return
        expense = self._selected_expense()
        if expense is None:
            messagebox.showinfo("Nothing selected", "Select a subscription in the list first.")
            return
        self._open_edit_dialog(expense)

    def _open_edit_dialog(self, expense) -> None:
        """Open the entry form on an existing subscription.

        Both the calendar's day list and the Subscriptions view edit through here,
        so the two cannot drift apart.
        """
        dialog = AddExpenseDialog(
            self.root,
            self.data_file,
            self.refresh_view,
            self.selected_date,
            self.expenses,
            theme_mode=self.theme_mode.get(),
            expense=expense,
            payment_sources=self.cards,
        )
        dialog.grab_set()
        self.root.wait_window(dialog)


class CardPaymentDialog(tk.Toplevel):
    """A whole year of one card's payments, in the application's own styling.

    This replaces a raw simpledialog prompt, which asked for one month at a
    time in unstyled Tk. A year at once is also the right shape for the real
    task: filling in what has already been paid so far this year.
    """

    MONTH_NAMES = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )

    def __init__(
        self,
        master: tk.Tk,
        data_file: Path,
        refresh_callback,
        card,
        year: int,
        theme_mode: str = "light",
    ) -> None:
        super().__init__(master)
        self.data_file = data_file
        self.refresh_callback = refresh_callback
        self.card = card
        self.year = year
        self.theme = WARM_DARK if theme_mode == "dark" else WARM_LIGHT
        self.title("Payments · " + card.name)
        self.configure(bg=self.theme["background"])
        self.resizable(False, False)
        self.option_add("*insertBackground", self.theme["input_cursor"])

        header = tk.Frame(self, bg=self.theme["background"])
        header.grid(row=0, column=0, columnspan=4, sticky="ew", padx=SPACE_5, pady=(SPACE_5, SPACE_2))
        tk.Label(
            header,
            text=card.name,
            bg=self.theme["background"],
            fg=self.theme["text"],
            font=display_font(16),
        ).pack(side="left", anchor="w")

        self.year_var = tk.StringVar(value=str(year))
        year_box = ttk.Combobox(
            header, textvariable=self.year_var, state="readonly", width=6,
            values=[str(y) for y in range(date.today().year - 5, date.today().year + 2)],
        )
        year_box.pack(side="right")
        year_box.bind("<<ComboboxSelected>>", self._change_year)

        tk.Label(
            self,
            text=(
                "Enter what you actually paid in each month. Leave a month empty if you did not pay "
                "it, or to clear one you recorded before."
            ),
            bg=self.theme["background"],
            fg=self.theme["text_muted"],
            font=text_font(9),
            justify="left",
            wraplength=430,
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=SPACE_5, pady=(0, SPACE_4))

        # Two columns of six months, so the dialog stays a sensible height.
        self.month_vars = {}
        grid = tk.Frame(self, bg=self.theme["background"])
        grid.grid(row=2, column=0, columnspan=4, sticky="ew", padx=SPACE_5)
        for index, name in enumerate(self.MONTH_NAMES):
            column = 0 if index < 6 else 2
            row = index if index < 6 else index - 6
            tk.Label(
                grid,
                text=name,
                bg=self.theme["background"],
                fg=self.theme["text_secondary"],
                font=text_font(10),
                width=10,
                anchor="w",
            ).grid(row=row, column=column, sticky="w", pady=SPACE_1, padx=(0, SPACE_2))

            variable = tk.StringVar()
            self.month_vars[index + 1] = variable
            entry = tk.Entry(
                grid,
                textvariable=variable,
                width=11,
                bg=self.theme["surface"],
                fg=self.theme["text"],
                font=text_font(10),
                insertbackground=self.theme["input_cursor"],
                relief="flat",
                highlightthickness=1,
                highlightbackground=self.theme["outline"],
                highlightcolor=self.theme["accent"],
                justify="right",
            )
            entry.grid(row=row, column=column + 1, sticky="w", pady=SPACE_1,
                       padx=(0, SPACE_5 if column == 0 else 0), ipady=4)

        self.total_label = tk.Label(
            self,
            text="",
            bg=self.theme["background"],
            fg=self.theme["text"],
            font=text_font(10, bold=True),
        )
        self.total_label.grid(row=3, column=0, columnspan=4, sticky="w", padx=SPACE_5, pady=(SPACE_4, 0))

        actions = tk.Frame(self, bg=self.theme["background"])
        actions.grid(row=4, column=0, columnspan=4, sticky="e", padx=SPACE_5, pady=(SPACE_3, SPACE_5))
        PillButton(actions, "Cancel", self.destroy, self.theme, variant="tonal").grid(row=0, column=0, padx=(0, SPACE_2))
        PillButton(actions, "Save payments", self.save_payments, self.theme, variant="filled").grid(row=0, column=1)

        self._load_year()
        for variable in self.month_vars.values():
            variable.trace_add("write", lambda *_args: self._update_total())
        self._update_total()

        if master is not None and master.winfo_viewable():
            self.transient(master)

    def _load_year(self) -> None:
        recorded = get_card_payments_for_year(self.data_file, self.card.id, self.year)
        for month, variable in self.month_vars.items():
            amount = recorded.get(month)
            variable.set("" if amount is None else format(amount, ".2f"))

    def _change_year(self, _event=None) -> None:
        """Switching year discards nothing: the previous year is already saved."""
        self.year = int(self.year_var.get())
        self._load_year()
        self._update_total()

    def _parse(self, text: str):
        """Returns (ok, value). An empty field is a valid instruction to clear."""
        cleaned = text.strip().lstrip("$").replace(",", "")
        if not cleaned:
            return True, None
        try:
            value = float(cleaned)
        except ValueError:
            return False, None
        if value < 0:
            return False, None
        return True, round(value, 2)

    def _update_total(self) -> None:
        total = 0.0
        months = 0
        for variable in self.month_vars.values():
            ok, value = self._parse(variable.get())
            if ok and value is not None:
                total += value
                months += 1
        word = "month" if months == 1 else "months"
        self.total_label.config(
            text=str(self.year) + " so far:  $" + format(total, ",.2f") + "  across " + str(months) + " " + word
        )

    def save_payments(self) -> None:
        parsed = {}
        for month, variable in self.month_vars.items():
            ok, value = self._parse(variable.get())
            if not ok:
                messagebox.showwarning(
                    "Check that amount",
                    "'" + variable.get().strip() + "' in " + self.MONTH_NAMES[month - 1]
                    + " is not an amount I can record.",
                )
                return
            parsed[month] = value

        for month, value in parsed.items():
            set_card_payment(self.data_file, self.card.id, self.year, month, value)
        self.refresh_callback()
        self.destroy()


class CardDialog(tk.Toplevel):
    """Add or edit a credit card.

    Deliberately shorter than the subscription form. A card has no amount and
    no cadence: it falls due once a month, and what is paid varies, so that is
    recorded separately when the payment actually happens.
    """

    def __init__(
        self,
        master: tk.Tk,
        data_file: Path,
        refresh_callback,
        theme_mode: str = "light",
        card=None,
    ) -> None:
        super().__init__(master)
        self.editing = card is not None
        self.original = card
        self.data_file = data_file
        self.refresh_callback = refresh_callback
        self.theme = WARM_DARK if theme_mode == "dark" else WARM_LIGHT
        self.title("Edit card" if self.editing else "Add card")
        self.option_add("*insertBackground", self.theme["input_cursor"])

        self.name_var = tk.StringVar(value=card.name if self.editing else "")
        self.kind_var = tk.StringVar(
            value=KIND_LABELS[card.kind if self.editing else KIND_CARD]
        )
        self.due_day_var = tk.StringVar(
            value=str(card.due_day) if self.editing and card.due_day else "1"
        )
        self.notes_var = tk.StringVar(value=card.notes if self.editing else "")
        self.color_var = tk.StringVar(value=card.color if self.editing else CARD_COLOUR)

        self.configure(bg=self.theme["background"])
        self.resizable(False, False)
        self.columnconfigure(0, weight=1)

        header = tk.Frame(self, bg=self.theme["background"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=SPACE_5, pady=(SPACE_5, SPACE_4))
        self.title_label = tk.Label(
            header,
            text="Edit card" if self.editing else "Add a card",
            bg=self.theme["background"],
            fg=self.theme["text"],
            font=display_font(16),
        )
        self.title_label.pack(side="left", anchor="w")

        ttk.Label(self, text="Name").grid(row=1, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        tk.Entry(
            self,
            textvariable=self.name_var,
            width=36,
            bg=self.theme["surface"],
            fg=self.theme["text"],
            font=text_font(10),
            insertbackground=self.theme["input_cursor"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.theme["outline"],
            highlightcolor=self.theme["accent"],
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=SPACE_5, pady=(0, SPACE_3), ipady=7)

        ttk.Label(self, text="This is a").grid(row=3, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        kind_box = ttk.Combobox(
            self, textvariable=self.kind_var, state="readonly", width=16,
            values=[KIND_LABELS[KIND_CARD], KIND_LABELS[KIND_BANK]],
        )
        kind_box.grid(row=4, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))
        kind_box.bind("<<ComboboxSelected>>", lambda _event: self._sync_kind())

        # Only a card has a bill of its own to pay. Money leaves a bank account
        # when a subscription bills, so a due day there would be a fiction.
        self.due_label = ttk.Label(self, text="Payment due on")
        self.due_label.grid(row=3, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_1))
        self.due_box = ttk.Combobox(
            self, textvariable=self.due_day_var, state="readonly", width=8,
            values=[str(day) for day in range(1, 32)],
        )
        self.due_box.grid(row=4, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_3))

        self.kind_hint = tk.Label(
            self,
            text="",
            bg=self.theme["background"],
            fg=self.theme["text_muted"],
            font=text_font(9),
            justify="left",
            wraplength=380,
        )
        self.kind_hint.grid(row=5, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))

        ttk.Label(self, text="Note (optional)").grid(row=6, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        tk.Entry(
            self,
            textvariable=self.notes_var,
            width=36,
            bg=self.theme["surface"],
            fg=self.theme["text"],
            font=text_font(10),
            insertbackground=self.theme["input_cursor"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.theme["outline"],
            highlightcolor=self.theme["accent"],
        ).grid(row=7, column=0, columnspan=2, sticky="ew", padx=SPACE_5, pady=(0, SPACE_3), ipady=7)

        # Cards share one colour so a month of due dates reads as one kind of
        # thing. The palette stays available for the odd card that genuinely
        # needs to stand out, but it is folded away rather than offered.
        ttk.Label(self, text="Colour").grid(row=8, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        colour_row = tk.Frame(self, bg=self.theme["background"])
        colour_row.grid(row=9, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_2))

        self.colour_preview = tk.Canvas(
            colour_row, width=26, height=26, bg=self.theme["background"], highlightthickness=0
        )
        self.colour_preview.pack(side="left", padx=(0, SPACE_3))

        self.colour_toggle = PillButton(
            colour_row, "Use a different colour", self._toggle_swatches, self.theme,
            variant="outlined", height=30,
        )
        self.colour_toggle.pack(side="left")

        swatches = tk.Frame(self, bg=self.theme["background"])
        swatches.grid(row=10, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))
        self.swatch_frame = swatches
        self.swatch_canvases = []
        for index, colour in enumerate((CARD_COLOUR,) + tuple(c for c in CATEGORY_COLOURS if c != CARD_COLOUR)):
            canvas = tk.Canvas(
                swatches, width=26, height=26, bg=self.theme["background"],
                highlightthickness=0, cursor="hand2",
            )
            canvas.grid(row=0, column=index, padx=(0, SPACE_2))
            canvas.bind("<Button-1>", lambda _event, value=colour: self._pick_colour(value))
            self.swatch_canvases.append((canvas, colour))

        # Only unfolded when an existing card already departs from the default.
        self.swatches_visible = self.editing and self.color_var.get() != CARD_COLOUR
        if not self.swatches_visible:
            swatches.grid_remove()
        self._paint_swatches()
        self._sync_kind()

        # A card is not spending, and the form is the right place to say so
        # rather than leaving the user to discover it from the totals.
        tk.Label(
            self,
            text=(
                "Card payments are never counted as spending. The purchases they settle "
                "are already tracked under Subscriptions."
            ),
            bg=self.theme["background"],
            fg=self.theme["text_muted"],
            font=text_font(9),
            justify="left",
            wraplength=380,
        ).grid(row=11, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))

        actions = tk.Frame(self, bg=self.theme["background"])
        actions.grid(row=12, column=0, columnspan=2, sticky="e", padx=SPACE_5, pady=(SPACE_2, SPACE_5))
        PillButton(actions, "Cancel", self.destroy, self.theme, variant="tonal").grid(row=0, column=0, padx=(0, SPACE_2))
        PillButton(actions, "Save card", self.save_card_entry, self.theme, variant="filled").grid(row=0, column=1)

        # Guard against the trap that made the login dialog invisible: Tk
        # withdraws a transient whose master is itself withdrawn.
        if master is not None and master.winfo_viewable():
            self.transient(master)

    def _toggle_swatches(self) -> None:
        self.swatches_visible = not self.swatches_visible
        if self.swatches_visible:
            self.swatch_frame.grid()
            self.colour_toggle.set_text("Use the usual colour")
        else:
            self.swatch_frame.grid_remove()
            self.color_var.set(CARD_COLOUR)
            self.colour_toggle.set_text("Use a different colour")
            self._paint_swatches()

    def _pick_colour(self, colour: str) -> None:
        self.color_var.set(colour)
        self._paint_swatches()

    def _paint_swatches(self) -> None:
        chosen = self.color_var.get()
        self.colour_preview.delete("all")
        self.colour_preview.create_oval(
            2, 2, 24, 24, fill=chosen, outline=mix(chosen, "#000000", 0.25), width=1
        )
        for canvas, colour in self.swatch_canvases:
            canvas.delete("all")
            outline = self.theme["text"] if colour == chosen else mix(colour, "#000000", 0.2)
            width = 3 if colour == chosen else 1
            canvas.create_oval(2, 2, 24, 24, fill=colour, outline=outline, width=width)

    def _selected_kind(self) -> str:
        return KIND_BANK if self.kind_var.get() == KIND_LABELS[KIND_BANK] else KIND_CARD

    def _sync_kind(self) -> None:
        """A bank account has no bill of its own, so it has no due day."""
        is_card = self._selected_kind() == KIND_CARD
        self.due_box.configure(state="readonly" if is_card else "disabled")
        if is_card:
            self.due_label.grid()
            self.due_box.grid()
            self.kind_hint.configure(
                text="Day of the month the bill is due. A day past the end of a short month "
                "falls on its last day."
            )
        else:
            self.due_label.grid_remove()
            self.due_box.grid_remove()
            self.kind_hint.configure(
                text="A bank account has no bill of its own — money leaves it when a "
                "subscription bills. It is here so a subscription can say where it is charged."
            )
        self.title_label.configure(
            text=("Edit " if self.editing else "Add a ")
            + ("card" if is_card else "bank account")
        )

    def save_card_entry(self) -> None:
        try:
            card = create_card(
                self.name_var.get(),
                self.due_day_var.get(),
                color=self.color_var.get(),
                notes=self.notes_var.get(),
                card_id=self.original.id if self.editing else None,
                kind=self._selected_kind(),
            )
        except ValueError as error:
            messagebox.showwarning("Check the card", str(error))
            return

        save_card(self.data_file, card)
        self.refresh_callback()
        self.destroy()


class AddExpenseDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Tk,
        data_file: Path,
        refresh_callback,
        initial_date: date,
        existing_expenses: list,
        theme_mode: str = "light",
        expense=None,
        payment_sources=None,
    ) -> None:
        super().__init__(master)
        self.editing = expense is not None
        # Read from the database rather than required from the caller, so an
        # older call site still opens a working dialog.
        self.payment_sources = (
            list(payment_sources) if payment_sources is not None else load_cards(data_file)
        )
        self.original = expense
        self.title("Edit subscription" if self.editing else "Add payment")
        self.data_file = data_file
        self.refresh_callback = refresh_callback
        self.existing_expenses = existing_expenses
        self.theme = WARM_DARK if theme_mode == "dark" else WARM_LIGHT
        self.option_add("*insertBackground", self.theme["input_cursor"])

        start_date = initial_date
        if self.editing:
            parsed_start = _parse_date(expense.date)
            if parsed_start is not None:
                start_date = parsed_start

        self.description_var = tk.StringVar(value=expense.description if self.editing else "")
        self.amount_var = tk.StringVar(
            value=("" if not self.editing or expense.amount is None else f"{expense.amount:.2f}")
        )
        self.date_var = tk.StringVar(value=start_date.strftime("%Y-%m-%d"))
        self.calendar_date = start_date
        self.category_var = tk.StringVar(value=expense.category if self.editing else "Subscription")
        self.expense_type_var = tk.StringVar(value=expense.expense_type if self.editing else "Fixed")
        # A subscription whose source was deleted falls back to "Not set"
        # rather than showing a name that no longer exists.
        existing_source = (
            payment_source_name(self.payment_sources, expense.paid_with) if self.editing else ""
        )
        self.source_var = tk.StringVar(value=existing_source or NO_PAYMENT_SOURCE)
        self.color_var = tk.StringVar(value=(expense.color if self.editing else "#f2c14e"))
        self.color_choices_visible = False
        self.cadence_var = tk.StringVar(
            value=CADENCE_LABELS[expense.cadence if self.editing else CADENCE_MONTHLY]
        )
        self.ends_on_var = tk.StringVar(value=(expense.ends_on or "") if self.editing else "")
        self.paid_now_var = tk.BooleanVar(value=False)

        self.configure(bg=self.theme["background"])
        self.resizable(False, False)

        header = tk.Frame(self, bg=self.theme["background"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=SPACE_5, pady=(SPACE_5, SPACE_4))
        tk.Label(
            header,
            text="Add new subscription",
            bg=self.theme["background"],
            fg=self.theme["text"],
            font=display_font(16),
        ).pack(side="left", anchor="w")

        ttk.Label(self, text="Description").grid(row=1, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        tk.Entry(
            self,
            textvariable=self.description_var,
            width=40,
            bg=self.theme["surface"],
            fg=self.theme["text"],
            font=text_font(10),
            insertbackground=self.theme["input_cursor"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.theme["outline"],
            highlightcolor=self.theme["accent"],
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=SPACE_5, pady=(0, SPACE_3), ipady=7)

        ttk.Label(self, text="Amount").grid(row=3, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        tk.Entry(
            self,
            textvariable=self.amount_var,
            width=22,
            bg=self.theme["surface"],
            fg=self.theme["text"],
            font=text_font(10),
            insertbackground=self.theme["input_cursor"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.theme["outline"],
            highlightcolor=self.theme["accent"],
        ).grid(row=4, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_3), ipady=7)
        ttk.Label(self, text="Date").grid(row=3, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_1))
        self.date_entry = DateEntry(
            self,
            textvariable=self.date_var,
            width=18,
            date_pattern="yyyy-mm-dd",
            background=self.theme["panel_alt"],
            foreground=self.theme["text"],
            bordercolor=self.theme["border"],
            headersbackground=self.theme["list_header"],
            selectbackground=self.theme["accent"],
            selectforeground="#ffffff",
            justify="left",
        )
        self.date_entry.grid(row=4, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_3))
        self.date_entry.set_date(self.calendar_date)
        self.date_entry.bind("<<DateEntrySelected>>", self._sync_calendar_date)

        ttk.Label(self, text="Category").grid(row=5, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        category_box = ttk.Combobox(self, textvariable=self.category_var, state="normal", width=20)
        category_box["values"] = self._suggested_categories()
        category_box.grid(row=6, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))

        # The field accepts free text; without a caption it looks read-only
        # like the Type field beneath it.
        tk.Label(
            self,
            text="Pick a category or type your own — new ones are remembered.",
            bg=self.theme["background"],
            fg=self.theme["text_muted"],
            font=text_font(9),
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))

        ttk.Label(self, text="Repeats").grid(row=8, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        self.cadence_box = ttk.Combobox(self, textvariable=self.cadence_var, state="readonly", width=20)
        self.cadence_box["values"] = [CADENCE_LABELS[name] for name in CADENCES]
        self.cadence_box.grid(row=9, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        self.cadence_box.bind("<<ComboboxSelected>>", lambda _event: self._sync_end_date_state())

        # A tick rather than an empty box, because DateEntry will not stay
        # empty: it snaps back to today when focus leaves, which would quietly
        # turn "still running" into "ended today" and drop the subscription out
        # of every future month.
        # Read the stored end date before the DateEntry is built: constructing
        # one overwrites its textvariable with today, so anything read
        # afterwards is the widget's default rather than the saved value.
        existing_end = _parse_date(self.ends_on_var.get())
        self.has_end_date = tk.BooleanVar(value=existing_end is not None)
        ttk.Checkbutton(
            self,
            text="Ends on a date",
            variable=self.has_end_date,
            command=self._sync_end_date_state,
        ).grid(row=8, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_1))

        self.ends_on_entry = DateEntry(
            self,
            textvariable=self.ends_on_var,
            width=18,
            date_pattern="yyyy-mm-dd",
            background=self.theme["panel_alt"],
            foreground=self.theme["text"],
            bordercolor=self.theme["border"],
            headersbackground=self.theme["list_header"],
            selectbackground=self.theme["accent"],
            selectforeground="#ffffff",
            justify="left",
        )
        if existing_end is not None:
            self.ends_on_entry.set_date(existing_end)
        self.ends_on_entry.grid(row=9, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_1))

        self.ends_on_hint = tk.Label(
            self,
            text="Leave “Ends on” empty while the subscription is still active; set it to the last "
            "billing date when you cancel.",
            bg=self.theme["background"],
            fg=self.theme["text_muted"],
            font=text_font(9),
            wraplength=430,
            justify="left",
        )
        self.ends_on_hint.grid(row=10, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))

        ttk.Label(self, text="Type").grid(row=11, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_1))
        type_box = ttk.Combobox(self, textvariable=self.expense_type_var, state="readonly", width=20)
        type_box["values"] = ["Fixed", "Variable"]
        type_box.grid(row=12, column=0, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))

        # Which card or bank account this is charged to. Purely a label: it
        # never moves money between subscriptions and cards.
        ttk.Label(self, text="Charged to").grid(row=11, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_1))
        self.source_box = ttk.Combobox(
            self, textvariable=self.source_var, state="readonly", width=20,
            values=[NO_PAYMENT_SOURCE] + [card.name for card in self.payment_sources],
        )
        self.source_box.grid(row=12, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_3))

        recurring_frame = tk.Frame(self, bg=self.theme["background"])
        recurring_frame.grid(row=12, column=1, sticky="w", padx=(SPACE_5, 0), pady=(0, SPACE_3))
        ttk.Checkbutton(
            recurring_frame,
            text="Mark as paid this month",
            variable=self.paid_now_var,
        ).pack(anchor="w")
        self._sync_end_date_state()

        color_panel = tk.Frame(self, bg=self.theme["background"])
        color_panel.grid(row=13, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(SPACE_2, SPACE_3))
        tk.Label(color_panel, text="Color", bg=self.theme["background"], fg=self.theme["text"], font=text_font(10)).pack(side="left", padx=(0, SPACE_2))
        self.color_preview = tk.Canvas(
            color_panel,
            width=26,
            height=26,
            bg=self.theme["background"],
            highlightthickness=0,
        )
        self.color_preview.pack(side="left", padx=(0, SPACE_2))
        self._paint_color_preview()
        self.color_toggle_button = PillButton(
            color_panel,
            "Choose color",
            self._toggle_color_choices,
            self.theme,
            variant="tonal",
            height=32,
        )
        self.color_toggle_button.pack(side="left")

        self.color_choices = tk.Frame(self, bg=self.theme["background"])
        self.color_choices.grid(row=14, column=0, columnspan=2, sticky="w", padx=SPACE_5, pady=(0, SPACE_3))
        for color in ["#f2c14e", "#d97745", "#668f80", "#5f7db8", "#8d6fb0"]:
            swatch = tk.Canvas(
                self.color_choices,
                width=28,
                height=28,
                bg=self.theme["background"],
                highlightthickness=0,
                cursor="hand2",
            )
            swatch.create_oval(2, 2, 25, 25, fill=color, outline=mix(color, "#000000", 0.15))
            swatch.pack(side="left", padx=(0, SPACE_2))
            swatch.bind("<Button-1>", lambda _event, chosen=color: self._set_color(chosen))
        self.custom_color_button = PillButton(
            self.color_choices,
            "Custom",
            self._pick_color,
            self.theme,
            variant="outlined",
            height=32,
        )
        self.custom_color_button.pack(side="left")
        self.color_choices.grid_remove()

        actions = tk.Frame(self, bg=self.theme["background"])
        actions.grid(row=15, column=0, columnspan=2, sticky="e", padx=SPACE_5, pady=(SPACE_2, SPACE_5))
        PillButton(actions, "Cancel", self.destroy, self.theme, variant="tonal").grid(row=0, column=0, padx=(0, SPACE_2))
        PillButton(actions, "Save subscription", self.save_expense, self.theme, variant="filled").grid(row=0, column=1)

    def _paint_color_preview(self) -> None:
        self.color_preview.delete("all")
        color = self.color_var.get()
        self.color_preview.create_oval(1, 1, 24, 24, fill=color, outline=mix(color, "#000000", 0.2))

    def _selected_source_id(self):
        """The chosen payment source as an id, or None for "Not set"."""
        chosen = self.source_var.get()
        if not chosen or chosen == NO_PAYMENT_SOURCE:
            return None
        match = next((card for card in self.payment_sources if card.name == chosen), None)
        return match.id if match else None

    def _suggested_categories(self) -> list[str]:
        # "Credit Card" is deliberately absent. Card payments settle purchases
        # already recorded here, so entering one as an expense counts the same
        # money twice. They belong in the Cards view.
        categories = ["Subscription", "Utility", "Entertainment", "Food", "Other"]
        for expense in self.existing_expenses:
            if expense.category not in categories:
                categories.append(expense.category)
        return categories

    def _set_color(self, color: str) -> None:
        self.color_var.set(color)
        self._paint_color_preview()
        if self.color_choices_visible:
            self.color_choices.grid_remove()
            self.color_choices_visible = False
            self.color_toggle_button.set_text("Choose color")

    def _toggle_color_choices(self) -> None:
        self.color_choices_visible = not self.color_choices_visible
        if self.color_choices_visible:
            self.color_choices.grid()
            self.color_toggle_button.set_text("Hide colors")
        else:
            self.color_choices.grid_remove()
            self.color_toggle_button.set_text("Choose color")

    def _pick_color(self) -> None:
        selected_color = colorchooser.askcolor(title="Choose a color")[1]
        if selected_color:
            self._set_color(selected_color)

    def _sync_calendar_date(self, _event=None) -> None:
        try:
            self.calendar_date = self.date_entry.get_date()
            self.date_var.set(self.calendar_date.strftime("%Y-%m-%d"))
        except Exception:
            return

    def _parse_amount(self) -> float | None:
        amount_text = self.amount_var.get().strip()
        if not amount_text:
            return None

        normalized = amount_text.replace(" ", "").replace("$", "")
        if "," in normalized and "." in normalized:
            normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(",", ".")

        try:
            return round(float(normalized), 2)
        except ValueError:
            return None

    def _selected_cadence(self) -> str:
        return LABELS_TO_CADENCE.get(self.cadence_var.get(), CADENCE_MONTHLY)

    def _sync_end_date_state(self) -> None:
        """A one-off payment has a single date, so an end date is meaningless."""
        is_once = self._selected_cadence() == CADENCE_ONCE
        if is_once:
            self.has_end_date.set(False)

        enabled = self.has_end_date.get() and not is_once
        self.ends_on_entry.configure(state="normal" if enabled else "disabled")
        if enabled:
            if _parse_date(self.ends_on_var.get()) is None:
                # Give the picker something to open on rather than a stale value.
                self.ends_on_entry.set_date(self.calendar_date)
        else:
            # Show nothing rather than today. A date sitting in a disabled box
            # reads as an end date that has been set. Safe to clear here because
            # a disabled widget cannot take focus, and it is focus-out that
            # makes a DateEntry restore itself.
            self.ends_on_var.set("")

        if is_once:
            hint = "A one-off payment happens once, on the date above."
        elif enabled:
            hint = ("Pick the last date it bills. Dates are year-month-day, and the box opens a "
                    "calendar.")
        else:
            hint = ("Leave this unticked while the subscription is still running. Tick it when you "
                    "cancel, and pick the last date it bills.")
        self.ends_on_hint.configure(text=hint)

    def save_expense(self) -> None:
        description = self.description_var.get().strip()
        if not description:
            messagebox.showwarning("Missing fields", "Please enter a description.")
            return

        amount = self._parse_amount()
        if self.amount_var.get().strip() and amount is None:
            messagebox.showwarning("Invalid amount", "Use a numeric amount, for example 9.99.")
            return

        start_date = _parse_date(self.date_var.get())
        if start_date is None:
            messagebox.showwarning("Invalid date", "Use YYYY-MM-DD format for the start date.")
            return
        self.calendar_date = start_date

        cadence = self._selected_cadence()
        ends_on_text = self.ends_on_var.get().strip() if self.has_end_date.get() else ""
        ends_on = None
        if ends_on_text and cadence != CADENCE_ONCE:
            ends_on_date = _parse_date(ends_on_text)
            if ends_on_date is None:
                messagebox.showwarning("Invalid date", "Use YYYY-MM-DD format for the end date, or leave it empty.")
                return
            if ends_on_date < start_date:
                messagebox.showwarning(
                    "Check the dates",
                    "The end date is before the start date, so this subscription would never bill.",
                )
                return
            ends_on = ends_on_date.isoformat()

        due_day = None if cadence in (CADENCE_ONCE, "weekly") else start_date.day
        expense = create_expense(
            description=description,
            amount=amount,
            expense_date=start_date.isoformat(),
            category=self.category_var.get().strip() or "Other",
            due_day=due_day,
            expense_type=self.expense_type_var.get().strip() or "Fixed",
            paid_with=self._selected_source_id(),
            color=self.color_var.get() or "#f2c14e",
            cadence=cadence,
            ends_on=ends_on,
            # Reuse the id when editing so the paid history survives the change.
            expense_id=self.original.id if self.editing else None,
        )

        if self.editing:
            update_expense(self.data_file, expense)
        else:
            add_expense(self.data_file, expense)

        if amount is not None and self.paid_now_var.get():
            set_expense_paid(self.data_file, expense.id, self.calendar_date.year, self.calendar_date.month, True)

        self.refresh_callback()
        self.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    resolve_fonts(root)
    data_file = get_app_data_file()
    create_schema(data_file)
    authenticated_user = _show_auth_dialog(root, data_file)

    if authenticated_user is None:
        root.destroy()
    else:
        app = ExpenseTrackerApp(root, data_file=data_file, username=authenticated_user)
        root.deiconify()
        root.mainloop()
