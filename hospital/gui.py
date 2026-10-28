"""Tkinter application assembled from focused screen groups."""
from __future__ import annotations
from typing import Dict, Optional
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from .context import initialize_system
from .gui_common import CommonGuiMixin
from .gui_doctor import DoctorGuiMixin
from .gui_staff import StaffGuiMixin
from .gui_theme import BACKGROUND, configure_theme
from .security import User


class HospitalGUI(CommonGuiMixin, DoctorGuiMixin, StaffGuiMixin, tk.Tk):
    """Desktop application; mixins group related screens without changing behavior."""

    def __init__(self):
        super().__init__()
        self.title("Hospital Management System")
        self.geometry("1100x740")
        self.minsize(900, 620)
        self.ctx = initialize_system()
        self.current_user: Optional[User] = None
        self.style = ttk.Style(self)
        self.base_theme = "clam"
        configure_theme(self.style)
        self.configure(bg=BACKGROUND)
        self.high_contrast_var = tk.BooleanVar(value=False)
        self.font_size_offset = 0
        self._base_fonts: Dict[str, int] = {}
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
            try:
                self._base_fonts[name] = tkfont.nametofont(name).cget("size")
            except tk.TclError:
                pass
        self.container = ttk.Frame(self, padding=28)
        self.container.pack(fill="both", expand=True)
        for i in range(2):
            self.container.columnconfigure(i, weight=1)
        self.summary_text: Optional[tk.Text] = None
        self.nurse_bed_text: Optional[tk.Text] = None
        self.configure_menu()
        self.bind_shortcuts()
        self.show_start()
