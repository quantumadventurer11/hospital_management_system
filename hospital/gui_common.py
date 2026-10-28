"""Shared Tkinter controls, dialogs, and formatting for the desktop UI."""
from __future__ import annotations
from datetime import datetime
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from .context import initialize_system
from .errors import NotFoundError, ValidationError
from .persistence import load_context_from_file, save_context_to_file
from .timezones import UTC, get_timezone
from .gui_theme import BACKGROUND, SURFACE, INK, ACCENT, BORDER, SOFT, configure_theme


class CommonGuiMixin:
    # ---------- Utility ----------
    def configure_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Session", command=self.reset_context)
        file_menu.add_command(label="Load...", command=self.load_context_dialog)
        file_menu.add_command(label="Save...", command=self.save_context_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Increase Font Size", command=self.increase_font_event, accelerator="Ctrl++")
        view_menu.add_command(label="Decrease Font Size", command=self.decrease_font_event, accelerator="Ctrl+-")
        view_menu.add_command(label="Reset Font Size", command=self.reset_font_event, accelerator="Ctrl+0")
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="High Contrast Mode",
            variable=self.high_contrast_var,
            command=self.on_high_contrast_menu,
            accelerator="Ctrl+Shift+H",
        )
        menubar.add_cascade(label="View", menu=view_menu)
        self.config(menu=menubar)
        self.menubar = menubar

    def bind_shortcuts(self) -> None:
        self.bind_all("<Control-s>", self.save_shortcut)
        self.bind_all("<Control-o>", self.load_shortcut)
        self.bind_all("<Control-n>", self.new_session_shortcut)
        self.bind_all("<Control-plus>", self.increase_font_event)
        self.bind_all("<Control-KP_Add>", self.increase_font_event)
        self.bind_all("<Control-minus>", self.decrease_font_event)
        self.bind_all("<Control-KP_Subtract>", self.decrease_font_event)
        self.bind_all("<Control-0>", self.reset_font_event)
        self.bind_all("<Control-Shift-H>", self.toggle_high_contrast_event)

    def save_shortcut(self, event=None):
        self.save_context_dialog()
        return "break"

    def load_shortcut(self, event=None):
        self.load_context_dialog()
        return "break"

    def new_session_shortcut(self, event=None):
        self.reset_context()
        return "break"

    def increase_font_event(self, event=None):
        self.adjust_font_size(1)
        return "break"

    def decrease_font_event(self, event=None):
        self.adjust_font_size(-1)
        return "break"

    def reset_font_event(self, event=None):
        self.reset_font_size()
        return "break"

    def adjust_font_size(self, delta: int) -> None:
        new_offset = max(-4, min(6, self.font_size_offset + delta))
        if new_offset == self.font_size_offset:
            return
        self.font_size_offset = new_offset
        self._apply_font_offset()

    def reset_font_size(self) -> None:
        self.font_size_offset = 0
        self._apply_font_offset()

    def _apply_font_offset(self) -> None:
        for name, base in self._base_fonts.items():
            try:
                tkfont.nametofont(name).configure(size=base + self.font_size_offset)
            except tk.TclError:
                continue

    def on_high_contrast_menu(self) -> None:
        self.apply_high_contrast(self.high_contrast_var.get())

    def toggle_high_contrast_event(self, event=None):
        new_state = not self.high_contrast_var.get()
        self.high_contrast_var.set(new_state)
        self.apply_high_contrast(new_state)
        return "break"

    def apply_high_contrast(self, enabled: bool) -> None:
        if enabled:
            self.tk_setPalette(
                background="#1a1a1a",
                foreground="#f5f5f5",
                activeBackground="#333333",
                activeForeground="#ffffff",
                highlightColor="#f5f5f5",
                highlightBackground="#1a1a1a",
            )
            configure_theme(self.style, high_contrast=True)
            self.configure(bg="#1a1a1a")
            self._update_text_widget_palette("#1a1a1a", "#f5f5f5")
        else:
            self.tk_setPalette(
                background=BACKGROUND,
                foreground=INK,
                activeBackground=SOFT,
                activeForeground=INK,
                highlightColor=ACCENT,
                highlightBackground=BORDER,
            )
            configure_theme(self.style)
            self.configure(bg=BACKGROUND)
            self._update_text_widget_palette(SURFACE, INK)
        self._apply_font_offset()

    def _update_text_widget_palette(self, bg: str, fg: str) -> None:
        widgets = [self.summary_text, getattr(self, "nurse_bed_text", None)]
        for widget in widgets:
            if widget:
                try:
                    widget.configure(bg=bg, fg=fg, insertbackground=fg)
                except tk.TclError:
                    pass

    def reset_context(self) -> None:
        if not messagebox.askyesno("New Session", "Start a new session? Unsaved data will be lost.", parent=self):
            return
        self.ctx = initialize_system()
        self.current_user = None
        self.summary_text = None
        self.nurse_bed_text = None
        self.show_toast("System reset to defaults.")
        self.show_start()

    def load_context_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Hospital Data",
            filetypes=[("Hospital data JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            ctx = load_context_from_file(path)
        except Exception as exc:
            self.show_message("Load Failed", str(exc), error=True)
            return
        if not messagebox.askyesno(
            "Replace Current Session",
            "Loading saved data replaces the current session. Unsaved changes will be lost. Continue?",
            parent=self,
        ):
            return
        self.ctx = ctx
        self.current_user = None
        self.summary_text = None
        self.nurse_bed_text = None
        self.show_toast(f"Loaded {os.path.basename(path)}.")
        self.show_start()

    def save_context_dialog(self) -> None:
        if not self.current_user or not self.ctx.auth.validate_session(
            self.current_user.user_id, self.current_user.session_token or ""
        ):
            self.show_message("Sign In Required", "Sign in before saving hospital data.", error=True)
            return
        path = filedialog.asksaveasfilename(
            title="Save Hospital Data",
            defaultextension=".json",
            filetypes=[("Hospital data JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            save_context_to_file(self.ctx, path)
        except Exception as exc:
            self.show_message("Save Failed", str(exc), error=True)
            return
        self.show_toast(f"Saved to {os.path.basename(path)}.")

    def prompt_save_new_account(self) -> None:
        if messagebox.askyesno(
            "Save New Account",
            "This account exists only in the current session until you save hospital data. "
            "Saved JSON is not encrypted; use synthetic data only. Save now?",
            parent=self,
        ):
            self.save_context_dialog()

    def clear_container(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def show_message(self, title: str, message: str, *, error: bool=False) -> None:
        if error:
            messagebox.showerror(title, message, parent=self)
        else:
            messagebox.showinfo(title, message, parent=self)

    def show_toast(self, message: str, duration: int=2500) -> None:
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        label = tk.Label(toast, text=message, bg="#333333", fg="white", padx=16, pady=8)
        label.pack()
        toast.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - toast.winfo_width()) // 2
        y = self.winfo_rooty() + self.winfo_height() - toast.winfo_height() - 40
        toast.geometry(f"+{x}+{y}")
        toast.after(duration, toast.destroy)

    def open_form(
        self,
        title: str,
        fields: List[Dict[str, Any]],
        on_submit: Callable[[Dict[str, Any]], bool],
    ) -> tk.Toplevel:
        win = tk.Toplevel(self)
        win.title(title)
        win.result = None  # type: ignore[attr-defined]
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        entries: Dict[str, Dict[str, Any]] = {}
        for row, field in enumerate(fields):
            label = ttk.Label(frame, text=field["label"])
            label.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
            widget_type = field.get("widget", "entry")
            required = field.get("required", False)
            initial = field.get("initial", "")
            if widget_type == "combobox":
                choices = field.get("choices", [])
                choice_map = {label: value for label, value in choices}
                var = tk.StringVar(value=initial or (choices[0][0] if choices else ""))
                widget = ttk.Combobox(frame, textvariable=var, values=list(choice_map.keys()), state="readonly")
                widget.grid(row=row, column=1, sticky="ew", pady=4)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": widget,
                    "var": var,
                    "choices": choice_map,
                    "required": required,
                }
            elif widget_type == "textarea":
                text_widget = tk.Text(frame, height=6, width=40)
                text_widget.grid(row=row, column=1, sticky="ew", pady=4)
                if initial:
                    text_widget.insert("1.0", initial)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": text_widget,
                    "required": required,
                }
            elif widget_type == "label":
                label_widget = ttk.Label(frame, text=initial, anchor="w")
                label_widget.grid(row=row, column=1, sticky="ew", pady=4)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": label_widget,
                    "value": initial,
                    "required": False,
                }
            else:
                var = tk.StringVar(value=initial)
                entry = ttk.Entry(frame, textvariable=var, show=field.get("show"))
                entry.grid(row=row, column=1, sticky="ew", pady=4)
                entries[field["name"]] = {
                    "type": widget_type,
                    "widget": entry,
                    "var": var,
                    "required": required,
                }
        frame.columnconfigure(1, weight=1)
        error_var = tk.StringVar()
        error_label = ttk.Label(frame, textvariable=error_var, foreground="#b22222")
        error_label.grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=(6, 0))

        def submit():
            data: Dict[str, Any] = {}
            error_var.set("")
            for meta in entries.values():
                widget = meta["widget"]
                try:
                    widget.configure(foreground="")
                except tk.TclError:
                    pass
            for name, meta in entries.items():
                widget_type = meta["type"]
                required = meta["required"]
                if widget_type == "label":
                    raw = meta.get("value", "")
                elif widget_type == "textarea":
                    raw = meta["widget"].get("1.0", "end").strip()
                elif widget_type == "combobox":
                    raw_label = meta["var"].get().strip()
                    if required and not raw_label:
                        error_var.set("Please complete all required fields.")
                        try:
                            meta["widget"].configure(foreground="#b22222")
                        except tk.TclError:
                            pass
                        return
                    choices = meta["choices"]
                    if raw_label and raw_label not in choices:
                        error_var.set("Invalid selection.")
                        return
                    raw = choices.get(raw_label, "")
                else:
                    raw = meta["var"].get().strip()
                if required and not raw:
                    error_var.set("Please complete all required fields.")
                    try:
                        meta["widget"].configure(foreground="#b22222")
                    except tk.TclError:
                        pass
                    return
                data[name] = raw
            try:
                success = on_submit(data)
            except ValidationError as exc:
                error_var.set(str(exc))
                return
            except Exception as exc:
                messagebox.showerror(title, str(exc), parent=win)
                return
            if success:
                win.result = data  # type: ignore[attr-defined]
                win.destroy()
            else:
                error_var.set("Please review the highlighted fields.")

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=len(fields)+1, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(button_bar, text="Cancel", command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(button_bar, text="Submit", command=submit).pack(side="right")
        win.transient(self)
        win.grab_set()
        fields_widgets = [meta["widget"] for meta in entries.values() if meta["type"] != "textarea"]
        if fields_widgets:
            fields_widgets[0].focus_set()
        return win

    def parse_date(self, value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            raise ValidationError("Use YYYY-MM-DD for dates.")

    def parse_datetime(self, value: str, tzname: str) -> datetime:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValidationError("Use YYYY-MM-DD HH:MM for date & time.") from exc
        tz = get_timezone(tzname)
        return dt.replace(tzinfo=tz)

    def get_current_doctor(self) -> Optional[Doctor]:
        if not self.current_user or not self.current_user.person_id:
            return None
        try:
            return self.ctx.doctors.get(self.current_user.person_id)
        except NotFoundError:
            return None

    def show_start(self) -> None:
        self.clear_container()
        ttk.Label(self.container, text="HOSPITAL OPERATIONS  /  EDUCATIONAL DEMO",
                  style="Eyebrow.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(16, 12))
        ttk.Label(self.container, text="A clearer view of care workflows",
                  style="Title.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(self.container,
                  text="Explore scheduling, records, billing, and inpatient tasks in one local desktop prototype.",
                  style="Subtitle.TLabel", wraplength=760).grid(
                      row=2, column=0, columnspan=2, sticky="w", pady=(10, 28))

        card = ttk.Frame(self.container, style="Card.TFrame", padding=28)
        card.grid(row=3, column=0, columnspan=2, sticky="ew")
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="Get started", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text="Choose a workspace or restore a synthetic saved session.",
                  style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 24))
        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="w")
        ttk.Button(actions, text="Staff Login", style="Primary.TButton",
                   command=self.open_login).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="Register New Physician",
                   command=lambda: self.show_register_physician(None)).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="Load Saved Data",
                   command=self.load_context_dialog).pack(side="left")
        ttk.Label(self.container,
                  text="Synthetic data only  •  Local JSON saves are not encrypted",
                  style="Subtitle.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(22, 0))
