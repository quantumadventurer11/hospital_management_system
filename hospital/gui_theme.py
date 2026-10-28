"""A small, reusable visual language for the desktop demo."""

from tkinter import ttk


BACKGROUND = "#F3F7FA"
SURFACE = "#FFFFFF"
INK = "#17324D"
MUTED = "#52697D"
ACCENT = "#007D80"
ACCENT_HOVER = "#00696C"
BORDER = "#D7E3E9"
SOFT = "#E6F3F2"


def configure_theme(style: ttk.Style, *, high_contrast: bool = False) -> None:
    """Apply the same styles to every screen and dialog."""
    style.theme_use("clam")
    if high_contrast:
        bg, surface, ink, muted, accent, border = (
            "#151515", "#202020", "#FFFFFF", "#FFFFFF", "#FFD84D", "#FFFFFF"
        )
        accent_text = "#111111"
    else:
        bg, surface, ink, muted, accent, border = (
            BACKGROUND, SURFACE, INK, MUTED, ACCENT, BORDER
        )
        accent_text = "#FFFFFF"

    style.configure("TFrame", background=bg)
    style.configure("Card.TFrame", background=surface, borderwidth=1, relief="solid")
    style.configure("TLabel", background=bg, foreground=ink, font=("Segoe UI", 11))
    style.configure("Eyebrow.TLabel", background=bg, foreground=accent,
                    font=("Segoe UI", 10, "bold"))
    style.configure("Title.TLabel", background=bg, foreground=ink,
                    font=("Segoe UI", 23, "bold"))
    style.configure("Subtitle.TLabel", background=bg, foreground=muted,
                    font=("Segoe UI", 11))
    style.configure("Card.TLabel", background=surface, foreground=ink,
                    font=("Segoe UI", 11))
    style.configure("CardTitle.TLabel", background=surface, foreground=ink,
                    font=("Segoe UI", 15, "bold"))
    style.configure("CardMuted.TLabel", background=surface, foreground=muted,
                    font=("Segoe UI", 10))
    style.configure("Metric.TLabel", background=surface, foreground=ink,
                    font=("Segoe UI", 22, "bold"))
    style.configure("TButton", background=surface, foreground=ink,
                    bordercolor=border, borderwidth=1, padding=(14, 9),
                    font=("Segoe UI", 10, "bold"))
    style.map("TButton", background=[("active", bg)],
              foreground=[("disabled", muted)])
    style.configure("Primary.TButton", background=accent, foreground=accent_text,
                    bordercolor=accent, borderwidth=1, padding=(16, 10),
                    font=("Segoe UI", 10, "bold"))
    style.map("Primary.TButton", background=[("active", ACCENT_HOVER if not high_contrast else "#FFE570")],
              foreground=[("active", accent_text), ("disabled", muted)])
    style.configure("TEntry", fieldbackground=surface, foreground=ink,
                    bordercolor=border, padding=8)
    style.configure("TCombobox", fieldbackground=surface, foreground=ink,
                    bordercolor=border, padding=7)
    style.configure("TNotebook", background=bg, borderwidth=0)
    style.configure("TNotebook.Tab", background=bg, foreground=ink,
                    padding=(18, 10), font=("Segoe UI", 10, "bold"))
    style.map("TNotebook.Tab", background=[("selected", surface)],
              foreground=[("selected", accent)])
    style.configure("TLabelframe", background=surface, bordercolor=border)
    style.configure("TLabelframe.Label", background=surface, foreground=ink,
                    font=("Segoe UI", 11, "bold"))
    style.configure("Treeview", background=surface, fieldbackground=surface,
                    foreground=ink, rowheight=28)
    style.map("Treeview", background=[("selected", accent)],
              foreground=[("selected", accent_text)])
