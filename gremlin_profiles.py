"""Validated character preferences and their ordinary Tk controls."""
import json
import re
import tkinter as tk
from tkinter import ttk

HATS = ("none", "cap", "beanie", "crown", "tophat", "bow")


def normalize_cast(value, roster):
    if not isinstance(value, str):
        return ""
    result = []
    for kind in value.split(","):
        kind = kind.strip()
        if kind in roster and kind not in result:
            result.append(kind)
    return ",".join(result)


def read_profiles(value, roster):
    try:
        raw = json.loads(value) if isinstance(value, str) and len(value) <= 20000 else {}
    except (ValueError, TypeError):
        raw = {}
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for kind in roster:
        row = raw.get(kind)
        if not isinstance(row, dict):
            continue
        nickname, color = row.get("nickname", ""), row.get("color", "")
        hat = row.get("hat", "none")
        item = {"nickname": " ".join(nickname.split())[:24] if isinstance(nickname, str) else "",
                "color": color.upper() if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "",
                "hat": hat if hat in HATS else "none"}
        allowed = row.get("weapons")
        if isinstance(allowed, list):
            item["weapons"] = list(dict.fromkeys(v for v in allowed[:80]
                                                 if isinstance(v, str) and len(v) < 30))
        clean[kind] = item
    return clean


def normalize_profiles(value, roster):
    return json.dumps(read_profiles(value, roster), ensure_ascii=True, sort_keys=True)


def selected_cast(cfg, roster):
    explicit = normalize_cast(cfg.get("cast", ""), roster)
    if explicit:
        return explicit.split(",")
    return list(roster[:max(1, min(len(roster), int(cfg["crowd"])))])


def apply_profile(f, cfg, roster, weapons, palette):
    row = read_profiles(cfg.get("profiles", "{}"), roster).get(f.kind, {})
    f.nickname = row.get("nickname") or f.kind.title()
    f.custom_color, f.hat = row.get("color", ""), row.get("hat", "none")
    f.per = dict(f.per)  # a personal loadout must not rewrite the shared temperament.
    if "weapons" in row:
        f.per["weapons"] = tuple(w for w in row["weapons"] if w in weapons)
    if f.custom_color:
        f.pal = palette(f.custom_color)


def draw_accessory(app, f, head, transform):
    hat = getattr(f, "scene_hat", None)
    if hat is None:
        hat = getattr(f, "hat", "none")
    if hat == "none":
        return
    app.layer("costume")
    hx, hy = head
    color = f.color()

    def stroke(points, width=3, ink=color):
        coords = []
        for x, y in points:
            coords.extend(transform(hx + x, hy + y))
        app.line(coords, ink, max(1, width * f.sc))

    if hat == "cap":
        stroke([(-9, -8), (-7, -14), (5, -14), (9, -8)], 5)
        stroke([(-9, -8), (16, -8)], 3)
    elif hat == "beanie":
        stroke([(-9, -7), (-7, -15), (0, -18), (7, -15), (9, -7)], 5)
        x, y = transform(hx, hy - 20)
        app.dot(x, y, 3 * f.sc, color)
    elif hat == "crown":
        stroke([(-10, -8), (-12, -19), (-5, -14), (0, -23),
                (5, -14), (12, -19), (10, -8), (-10, -8)], 3, "#FFD35C")
    elif hat == "tophat":
        stroke([(-13, -8), (13, -8)], 3)
        stroke([(-8, -9), (-8, -25), (8, -25), (8, -9)], 5)
        stroke([(-8, -13), (8, -13)], 3, "#FFD35C")
    elif hat == "bow":
        stroke([(-3, -11), (-12, -17), (-12, -6), (3, -11),
                (12, -17), (12, -6), (-3, -11)], 3)


class ProfilesPanel:
    """Edits serialized preferences without replacing unsaved fields on Apply."""
    def __init__(self, parent, variables, roster, weapons):
        self.variables, self.roster, self.weapons = variables, roster, weapons
        self.dirty, self.loading = False, True
        self.active = roster[0]
        self.kind = tk.StringVar(value=self.active)
        self.automatic = tk.BooleanVar(value=not variables["cast"].get())
        self.selected = {k: tk.BooleanVar(value=k in variables["cast"].get().split(",")) for k in roster}
        self.nickname, self.color, self.hat = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.defaults = tk.BooleanVar(value=True)
        self.allowed = {w: tk.BooleanVar() for w in weapons}
        self.note = tk.StringVar()
        bg, fg = "#171B2C", "#E6ECFF"
        tk.Checkbutton(parent, text="Automatic cast (use How many of them)", variable=self.automatic,
                       command=self.cast_changed, bg=bg, fg=fg, selectcolor="#0E1120").pack(anchor="w", padx=12)
        castbox = tk.Frame(parent, bg=bg)
        castbox.pack(fill="x", padx=12)
        for i, kind in enumerate(roster):
            tk.Checkbutton(castbox, text=kind.title(), variable=self.selected[kind],
                           command=self.cast_changed, bg=bg, fg=fg, selectcolor="#0E1120").grid(
                               row=i // 5, column=i % 5, sticky="w")
        form = tk.Frame(parent, bg=bg)
        form.pack(fill="x", padx=14, pady=8)
        ttk.Combobox(form, textvariable=self.kind, values=roster, state="readonly", width=15).grid(row=0, column=0)
        self.kind.trace_add("write", self.choose)
        for row, (label, variable) in enumerate((("Nickname", self.nickname), ("Halo colour (#RRGGBB)", self.color)), 1):
            tk.Label(form, text=label, bg=bg, fg=fg).grid(row=row, column=0, sticky="w")
            tk.Entry(form, textvariable=variable, width=25, bg="#0E1120", fg=fg,
                     insertbackground=fg, relief="flat", highlightthickness=1,
                     highlightbackground="#2A3150", highlightcolor="#8FA0CC").grid(
                         row=row, column=1, sticky="w", padx=8, pady=1)
        tk.Label(form, text="Hat", bg=bg, fg=fg).grid(row=3, column=0, sticky="w")
        ttk.Combobox(form, textvariable=self.hat, values=HATS, state="readonly", width=22).grid(row=3, column=1, padx=8)
        tk.Checkbutton(parent, text="Use this character's default weapons", variable=self.defaults,
                       bg=bg, fg=fg, selectcolor="#0E1120").pack(anchor="w", padx=12)
        box = tk.Frame(parent, bg=bg)
        box.pack(fill="x", padx=12)
        for i, weapon in enumerate(weapons):
            tk.Checkbutton(box, text=weapon.title(), variable=self.allowed[weapon], bg=bg,
                           fg=fg, selectcolor="#0E1120").grid(row=i // 5, column=i % 5, sticky="w")
        tk.Label(parent, text="Turn off default weapons to use the checked list; none means no fighting.",
                 bg=bg, fg="#8FA0CC", wraplength=530).pack(padx=14, pady=5)
        tk.Label(parent, textvariable=self.note, bg=bg, fg="#FFD35C").pack(pady=3)
        for var in [self.nickname, self.color, self.hat, self.defaults] + list(self.allowed.values()):
            var.trace_add("write", self.changed)
        self.load()

    def changed(self, *_):
        if not self.loading:
            self.dirty = True

    def cast_changed(self):
        if self.automatic.get():
            self.variables["cast"].set("")
            self.note.set("Cast count follows the Behaviour slider.")
        else:
            chosen = [k for k in self.roster if self.selected[k].get()]
            if not chosen:
                chosen = [self.active]
                self.selected[self.active].set(True)
            self.variables["cast"].set(",".join(chosen))
            self.variables["crowd"].set(len(chosen))
            self.note.set("%d selected; their records stay with each character." % len(chosen))

    def choose(self, *_):
        self.flush()
        self.active = self.kind.get()
        self.load()

    def load(self):
        self.loading = True
        row = read_profiles(self.variables["profiles"].get(), self.roster).get(self.active, {})
        self.nickname.set(row.get("nickname", ""))
        self.color.set(row.get("color", ""))
        self.hat.set(row.get("hat", "none"))
        self.defaults.set("weapons" not in row)
        for w, var in self.allowed.items():
            var.set(w in row.get("weapons", []))
        self.loading, self.dirty = False, False

    def flush(self):
        if not self.dirty:
            return
        data = read_profiles(self.variables["profiles"].get(), self.roster)
        row = dict(nickname=self.nickname.get(), color=self.color.get(), hat=self.hat.get())
        if not self.defaults.get():
            row["weapons"] = [w for w, var in self.allowed.items() if var.get()]
        data[self.active] = row
        self.variables["profiles"].set(normalize_profiles(json.dumps(data), self.roster))
        self.dirty = False
