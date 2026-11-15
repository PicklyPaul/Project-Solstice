import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
import os
import math
import threading
import random
import numpy as np
from datetime import datetime, timedelta
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from LLSN import Horizon, lunar_elev

# Global variables storing the user's coordinate and date inputs
USER_X = 0.0
USER_Y = 0.0
USER_START = ""
USER_END = ""


def get_terrain_horizon(az_deg, lat_deg, lon_deg):
    """
    Reads the real NASA LOLA 360° horizon profile from 'horizon_360.csv' if available.
    Falls back to a procedural horizon model only when running offline without LOLA data.
    """
    h_file = os.path.join(os.getcwd(), "horizon_360.csv")
    if os.path.exists(h_file):
        try:
            az_list = []
            el_list = []
            with open(h_file, mode="r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    az_list.append(float(row["AZ"]))
                    el_list.append(float(row["Terrain_EL"]))
            if len(az_list) >= 2:
                return np.interp(np.asarray(az_deg) % 360.0, np.array(az_list), np.array(el_list), period=360.0)
        except Exception:
            pass

    # Offline fallback procedural terrain
    rad = np.deg2rad(az_deg)
    seed = abs(lat_deg * 0.3 + lon_deg * 0.1) + 1.2
    base = -0.3 if abs(lat_deg) > 75 else 0.1
    amp = 1.6 if abs(lat_deg) > 75 else 0.4
    ridge1 = np.sin(rad * 2.0 + seed) * 0.55
    ridge2 = np.cos(rad * 5.0 - seed * 1.7) * 0.30
    ridge3 = np.sin(rad * 11.0 + seed * 3.1) * 0.15
    return base + amp * (ridge1 + ridge2 + ridge3)


class LunarCSVViewerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PROJECT Solstice")
        self.geometry("1320x880")
        self.configure(bg="#03050c")

        # Slight window-level translucency for a sleek HUD glass effect (0.96 = 96% opaque)
        try:
            self.attributes("-alpha", 0.96)
        except Exception:
            pass

        # Data storage
        self.rows = []
        self.current_idx = 0
        self.csv_path = os.path.join(os.getcwd(), "epher.csv")

        # Animation & logo state
        self.is_playing = False
        self.play_speed = 1
        self.pulse_phase = 0.0
        self.stars = []
        self.logo_img = None

        self._load_optional_logo()
        self._setup_styles()
        self._build_ui()
        self._init_starfield()
        self._animate_hud()

    def _load_optional_logo(self):
        """Loads 'spaceapps_logo.png' if present in the folder; otherwise draws the vector emblem."""
        logo_path = os.path.join(os.getcwd(), "spaceapps_logo.png")
        if os.path.exists(logo_path):
            try:
                raw_img = tk.PhotoImage(file=logo_path)
                scale = max(1, raw_img.height() // 48)
                self.logo_img = raw_img.subsample(scale, scale)
            except Exception:
                self.logo_img = None

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        bg_main = "#03050c"
        bg_panel = "#070c18"
        bg_card = "#0c1426"
        fg_text = "#f8fafc"

        style.configure("TFrame", background=bg_main)
        style.configure("Panel.TFrame", background=bg_panel)
        style.configure("Card.TFrame", background=bg_card)

        style.configure("TLabel", background=bg_panel, foreground=fg_text, font=("Segoe UI", 9))
        style.configure("Section.TLabel", background=bg_panel, foreground="#38bdf8", font=("Consolas", 9, "bold"))
        style.configure("CardTitle.TLabel", background=bg_card, foreground="#7dd3fc", font=("Consolas", 8, "bold"))
        style.configure("CardVal.TLabel", background=bg_card, foreground="#38bdf8", font=("Consolas", 15, "bold"))
        style.configure("CardValSun.TLabel", background=bg_card, foreground="#fbbf24", font=("Consolas", 15, "bold"))

        style.configure("TButton", background="#0369a1", foreground="white", font=("Consolas", 9, "bold"), padding=6, borderwidth=0)
        style.map("TButton", background=[("active", "#0ea5e9")])

        style.configure("Play.TButton", background="#047857", foreground="white", font=("Consolas", 9, "bold"), padding=6, borderwidth=0)
        style.map("Play.TButton", background=[("active", "#10b981")])

        style.configure("Secondary.TButton", background="#0f1b33", foreground="#7dd3fc", font=("Consolas", 8, "bold"), padding=5)
        style.map("Secondary.TButton", background=[("active", "#1e3a5f")])

        style.configure("Space.Horizontal.TProgressbar", troughcolor="#0c1426", background="#38bdf8", bordercolor="#070c18", lightcolor="#7dd3fc", darkcolor="#0284c7")

    def _build_ui(self):
        # --- ANIMATED SPACE HEADER BANNER ---
        self.header_canvas = tk.Canvas(self, height=68, bg="#03050c", highlightthickness=0)
        self.header_canvas.pack(fill="x", padx=16, pady=(10, 8))

        btn_frame = tk.Frame(self.header_canvas, bg="#03050c")
        self.header_canvas.create_window(1285, 34, window=btn_frame, anchor="e")

        ttk.Button(btn_frame, text="[+] Sample epher.csv", style="Secondary.TButton", command=self._create_sample_csv).pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="[📂] Load CSV", style="Secondary.TButton", command=self._browse_csv).pack(side="left")

        # --- MAIN WORKSPACE ---
        workspace = ttk.Frame(self)
        workspace.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # Left Panel: Coordinate & Date Input, Scrubber & Feasibility Assessment
        left_panel = ttk.Frame(workspace, width=375)
        left_panel.pack(side="left", fill="y", padx=(0, 12))
        left_panel.pack_propagate(False)

        # 1. Coordinate & Date Input Box
        input_border = tk.Frame(left_panel, bg="#1d4ed8", padx=1, pady=1)
        input_border.pack(fill="x", pady=(0, 10))
        input_box = ttk.Frame(input_border, style="Panel.TFrame", padding=12)
        input_box.pack(fill="both")

        ttk.Label(input_box, text="◈ 01 // TARGET LANDING COORDINATES", style="Section.TLabel").pack(anchor="w", pady=(0, 8))

        coord_row = ttk.Frame(input_box, style="Panel.TFrame")
        coord_row.pack(fill="x", pady=(0, 8))

        x_frame = ttk.Frame(coord_row, style="Panel.TFrame")
        x_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(x_frame, text="LONGITUDE X (°E):", font=("Consolas", 8), foreground="#7dd3fc").pack(anchor="w")
        self.x_var = tk.StringVar(value="129.78")
        tk.Entry(x_frame, textvariable=self.x_var, bg="#0c1426", fg="#38bdf8", insertbackground="#38bdf8", relief="flat", highlightthickness=1, highlightbackground="#1e3a5f", font=("Consolas", 10, "bold")).pack(fill="x", ipady=4)

        y_frame = ttk.Frame(coord_row, style="Panel.TFrame")
        y_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(y_frame, text="LATITUDE Y (°N/-°S):", font=("Consolas", 8), foreground="#7dd3fc").pack(anchor="w")
        self.y_var = tk.StringVar(value="-89.54")
        tk.Entry(y_frame, textvariable=self.y_var, bg="#0c1426", fg="#38bdf8", insertbackground="#38bdf8", relief="flat", highlightthickness=1, highlightbackground="#1e3a5f", font=("Consolas", 10, "bold")).pack(fill="x", ipady=4)

        date_row = ttk.Frame(input_box, style="Panel.TFrame")
        date_row.pack(fill="x", pady=(0, 10))

        start_frame = ttk.Frame(date_row, style="Panel.TFrame")
        start_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(start_frame, text="EPOCH START (UTC):", font=("Consolas", 8), foreground="#7dd3fc").pack(anchor="w")
        self.start_var = tk.StringVar(value="2026-11-14")
        tk.Entry(start_frame, textvariable=self.start_var, bg="#0c1426", fg="#e2e8f0", insertbackground="#38bdf8", relief="flat", highlightthickness=1, highlightbackground="#1e3a5f", font=("Consolas", 10)).pack(fill="x", ipady=4)

        end_frame = ttk.Frame(date_row, style="Panel.TFrame")
        end_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(end_frame, text="EPOCH END (UTC):", font=("Consolas", 8), foreground="#7dd3fc").pack(anchor="w")
        self.end_var = tk.StringVar(value="2026-12-14")
        tk.Entry(end_frame, textvariable=self.end_var, bg="#0c1426", fg="#e2e8f0", insertbackground="#38bdf8", relief="flat", highlightthickness=1, highlightbackground="#1e3a5f", font=("Consolas", 10)).pack(fill="x", ipady=4)

        self.apply_btn = ttk.Button(input_box, text="ACQUIRE TELEMETRY & LOAD", command=self._on_apply_inputs)
        self.apply_btn.pack(fill="x", pady=(0, 8))

        self.progress_bar = ttk.Progressbar(input_box, orient="horizontal", mode="indeterminate", style="Space.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", pady=(0, 4))

        self.file_status_lbl = ttk.Label(input_box, text="STANDBY // Awaiting target coordinates.", foreground="#64748b", font=("Consolas", 8), wraplength=340)
        self.file_status_lbl.pack(anchor="w", pady=(2, 0))

        # 2. Time Scrubber, Playback & Selected Timestamp Readout
        readout_border = tk.Frame(left_panel, bg="#1d4ed8", padx=1, pady=1)
        readout_border.pack(fill="x", pady=(0, 10))
        readout_box = ttk.Frame(readout_border, style="Panel.TFrame", padding=12)
        readout_box.pack(fill="both")

        ttk.Label(readout_box, text="◈ 02 // ORBITAL TIMELINE & TELEMETRY", style="Section.TLabel").pack(anchor="w", pady=(0, 6))

        self.dt_display_lbl = ttk.Label(readout_box, text="UTC EPOCH: --", foreground="#f8fafc", font=("Consolas", 10, "bold"))
        self.dt_display_lbl.pack(anchor="w", pady=(0, 4))

        self.slider_var = tk.IntVar(value=0)
        self.time_slider = tk.Scale(
            readout_box, from_=0, to=0, orient="horizontal", variable=self.slider_var,
            showvalue=False, bg="#070c18", troughcolor="#0c1426", highlightthickness=0,
            activebackground="#38bdf8", command=self._on_slider_move
        )
        self.time_slider.pack(fill="x", pady=(2, 8))

        play_row = ttk.Frame(readout_box, style="Panel.TFrame")
        play_row.pack(fill="x", pady=(0, 10))

        self.play_btn = ttk.Button(play_row, text="▶ PLAY ORBIT", style="Play.TButton", command=self._toggle_playback)
        self.play_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.speed_btn = ttk.Button(play_row, text="SPEED: 1x", style="Secondary.TButton", command=self._cycle_speed)
        self.speed_btn.pack(side="right")

        cards_row = ttk.Frame(readout_box, style="Panel.TFrame")
        cards_row.pack(fill="x")

        sun_card_wrap = tk.Frame(cards_row, bg="#1e3a5f", padx=1, pady=1)
        sun_card_wrap.pack(side="left", fill="both", expand=True, padx=(0, 5))
        sun_card = ttk.Frame(sun_card_wrap, style="Card.TFrame", padding=10)
        sun_card.pack(fill="both", expand=True)
        ttk.Label(sun_card, text="☀ SOLAR ARRAY", style="CardTitle.TLabel").pack(anchor="w")
        self.el_val_lbl = ttk.Label(sun_card, text="-- °", style="CardValSun.TLabel")
        self.el_val_lbl.pack(anchor="w", pady=(2, 0))
        self.horizon_status_lbl = ttk.Label(sun_card, text="AZ: --", background="#0c1426", foreground="#94a3b8", font=("Consolas", 8))
        self.horizon_status_lbl.pack(anchor="w", pady=(2, 0))

        earth_card_wrap = tk.Frame(cards_row, bg="#1e3a5f", padx=1, pady=1)
        earth_card_wrap.pack(side="left", fill="both", expand=True, padx=(5, 0))
        earth_card = ttk.Frame(earth_card_wrap, style="Card.TFrame", padding=10)
        earth_card.pack(fill="both", expand=True)
        ttk.Label(earth_card, text="🌍 EARTH DTE", style="CardTitle.TLabel").pack(anchor="w")
        self.earth_el_lbl = ttk.Label(earth_card, text="-- °", style="CardVal.TLabel")
        self.earth_el_lbl.pack(anchor="w", pady=(2, 0))
        self.earth_status_lbl = ttk.Label(earth_card, text="AZ: --", background="#0c1426", foreground="#94a3b8", font=("Consolas", 8))
        self.earth_status_lbl.pack(anchor="w", pady=(2, 0))

        # 3. Landing Site Optimality Assessment
        assess_border = tk.Frame(left_panel, bg="#1d4ed8", padx=1, pady=1)
        assess_border.pack(fill="both", expand=True)
        assess_box = ttk.Frame(assess_border, style="Panel.TFrame", padding=12)
        assess_box.pack(fill="both", expand=True)

        ttk.Label(assess_box, text="◈ 03 // LANDING SITE FEASIBILITY", style="Section.TLabel").pack(anchor="w", pady=(0, 8))

        verdict_wrap = tk.Frame(assess_box, bg="#1e3a5f", padx=1, pady=1)
        verdict_wrap.pack(fill="both", expand=True)
        verdict_card = ttk.Frame(verdict_wrap, style="Card.TFrame", padding=12)
        verdict_card.pack(fill="both", expand=True)

        self.verdict_badge_lbl = ttk.Label(
            verdict_card,
            text="AWAITING TELEMETRY",
            background="#0c1426",
            foreground="#64748b",
            font=("Consolas", 11, "bold")
        )
        self.verdict_badge_lbl.pack(anchor="w", pady=(0, 6))

        self.verdict_stats_lbl = ttk.Label(
            verdict_card,
            text="SUN VIS: --%  |  EARTH DTE: --%",
            background="#0c1426",
            foreground="#38bdf8",
            font=("Consolas", 8, "bold")
        )
        self.verdict_stats_lbl.pack(anchor="w", pady=(0, 8))

        self.verdict_desc_lbl = ttk.Label(
            verdict_card,
            text="Enter target lunar coordinates and mission window above, then acquire telemetry to evaluate solar power availability, Direct-to-Earth (DTE) line-of-sight, and landing viability.",
            background="#0c1426",
            foreground="#cbd5e1",
            font=("Segoe UI", 9),
            wraplength=318,
            justify="left"
        )
        self.verdict_desc_lbl.pack(anchor="w", fill="both", expand=True)

        # --- RIGHT PANEL: VISUALIZATIONS ---
        right_border = tk.Frame(workspace, bg="#1d4ed8", padx=1, pady=1)
        right_border.pack(side="left", fill="both", expand=True)
        right_panel = ttk.Frame(right_border, style="Panel.TFrame", padding=10)
        right_panel.pack(fill="both", expand=True)

        self.fig = Figure(figsize=(8.5, 6.2), dpi=100, facecolor="#070c18")
        self.ax_sky = self.fig.add_subplot(211, facecolor="#040711")
        self.ax_timeline = self.fig.add_subplot(212, facecolor="#040711")
        self.fig.subplots_adjust(left=0.08, right=0.97, top=0.92, bottom=0.10, hspace=0.38)

        self.canvas = FigureCanvasTkAgg(self.fig, master=right_panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self._draw_empty_charts()

    # =========================================================================
    # NASA SPACE APPS EMBLEM & ANIMATED SPACE HEADER
    # =========================================================================
    def _draw_nasa_space_apps_logo(self, x, y):
        """Renders the NASA Space Apps Challenge emblem on the top-left header canvas."""
        if self.logo_img is not None:
            self.header_canvas.create_image(x + 26, y + 25, image=self.logo_img, tags="hud")
            return

        # 1. Deep Cosmic Navy Circular Badge with dual orbital borders
        self.header_canvas.create_oval(
            x + 1, y + 1, x + 51, y + 51,
            fill="#071739", outline="#2E96F5", width=1.6, tags="hud"
        )
        self.header_canvas.create_oval(
            x + 4, y + 4, x + 48, y + 48,
            fill="", outline="#0960E1", width=1.0, tags="hud"
        )

        # 2. Tilted Cyan/Blue Orbital Swoosh Ring
        self.header_canvas.create_arc(
            x - 4, y + 15, x + 56, y + 38,
            start=165, extent=210, style="arc", outline="#00B4D8", width=2.2, tags="hud"
        )

        # 3. Stylized Space Apps 'A' Peak + Red/Orange Accent Swoop
        self.header_canvas.create_line(
            x + 13, y + 40, x + 26, y + 9, x + 39, y + 40,
            fill="#ffffff", width=2.8, capstyle="round", joinstyle="round", tags="hud"
        )
        self.header_canvas.create_arc(
            x + 8, y + 22, x + 45, y + 35,
            start=195, extent=155, style="arc", outline="#E43700", width=2.4, tags="hud"
        )

        # 4. Crisp 4-Point Star Sparkles
        for sx, sy, r in [(x + 13, y + 14, 2.8), (x + 40, y + 16, 2.0)]:
            self.header_canvas.create_line(sx - r, sy, sx + r, sy, fill="#ffffff", width=1.2, tags="hud")
            self.header_canvas.create_line(sx, sy - r, sx, sy + r, fill="#ffffff", width=1.2, tags="hud")

    def _init_starfield(self):
        rng = random.Random(42)
        for _ in range(75):
            self.stars.append({
                "x": rng.uniform(0, 1400),
                "y": rng.uniform(4, 62),
                "size": rng.choice([1, 1.5, 2.2]),
                "speed": rng.uniform(0.15, 0.65),
                "color": rng.choice(["#ffffff", "#bae6fd", "#fef08a", "#94a3b8"])
            })

    def _animate_hud(self):
        """Continuously animates the top starfield banner and updates playback."""
        self.pulse_phase += 0.14
        w = max(self.header_canvas.winfo_width(), 1280)

        self.header_canvas.delete("hud")

        for s in self.stars:
            s["x"] = (s["x"] - s["speed"]) % w
            self.header_canvas.create_oval(
                s["x"], s["y"], s["x"] + s["size"], s["y"] + s["size"],
                fill=s["color"], outline="", tags="hud"
            )

        # Render NASA Space Apps emblem in the top-left corner
        self._draw_nasa_space_apps_logo(12, 8)

        self.header_canvas.create_text(
            74, 23, text="PROJECT SOLSTICE: Lunar Landing Site Assessment",
            fill="#ffffff", font=("Consolas", 13, "bold"), anchor="w", tags="hud"
        )
        status_txt = "● ORBITAL PLAYBACK ACTIVE" if self.is_playing else "● TELEMETRY LINK READY // JPL HORIZONS + LOLA DEM"
        status_col = "#34d399" if self.is_playing else "#38bdf8"
        self.header_canvas.create_text(
            74, 43, text=status_txt,
            fill=status_col, font=("Consolas", 8, "bold"), anchor="w", tags="hud"
        )

        if self.is_playing and self.rows:
            next_idx = (self.current_idx + self.play_speed) % len(self.rows)
            self.slider_var.set(next_idx)
            self._select_row(next_idx)

        self.after(55, self._animate_hud)

    def _toggle_playback(self):
        if not self.rows:
            messagebox.showinfo("No Data", "Load or generate ephemeris data first before starting playback.")
            return
        self.is_playing = not self.is_playing
        self.play_btn.config(text="⏸ PAUSE ORBIT" if self.is_playing else "▶ PLAY ORBIT")

    def _cycle_speed(self):
        speeds = [1, 2, 5]
        nxt = speeds[(speeds.index(self.play_speed) + 1) % len(speeds)]
        self.play_speed = nxt
        self.speed_btn.config(text=f"SPEED: {nxt}x")

    # =========================================================================
    # COORDINATE, DATE & CSV HANDLING
    # =========================================================================
    def _on_apply_inputs(self):
        global USER_X, USER_Y, USER_START, USER_END
        self.is_playing = False
        self.play_btn.config(text="▶ PLAY ORBIT")

        try:
            USER_X = float(self.x_var.get().strip())
            USER_Y = float(self.y_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Coordinates", "Please enter valid numeric values for X and Y coordinates.")
            return

        start_str = self.start_var.get().strip()
        end_str = self.end_var.get().strip()
        if not start_str or not end_str:
            messagebox.showerror("Missing Dates", "Please enter both a Start Date and an End Date.")
            return

        try:
            dt_start = datetime.strptime(start_str, "%Y-%m-%d")
            dt_end = datetime.strptime(end_str, "%Y-%m-%d")
            if dt_end < dt_start:
                messagebox.showerror("Invalid Date Range", "End Date must be on or after Start Date.")
                return
        except ValueError:
            messagebox.showerror("Invalid Date Format", "Please enter dates in YYYY-MM-DD format (e.g., 2026-11-14).")
            return

        USER_START = start_str
        USER_END = end_str

        self.apply_btn.config(state="disabled")
        self.progress_bar.start(10)
        self.file_status_lbl.config(text="UPLINKING // Querying NASA LOLA & Horizons...", foreground="#38bdf8")

        threading.Thread(target=self._run_backend_task, daemon=True).start()

    def _run_backend_task(self):
        global USER_X, USER_Y, USER_START, USER_END
        try:
            Horizon(USER_X, USER_Y, lunar_elev(USER_Y, USER_X), USER_START, USER_END, 10)

            epher_file = os.path.join(os.getcwd(), "epher.csv")
            if os.path.exists(epher_file):
                self.after(0, lambda: self._finish_loading(epher_file, success=True))
            else:
                self.after(0, lambda: self._finish_loading(None, success=False, error_msg="'epher.csv' was not found in project folder."))
        except Exception as e:
            self.after(0, lambda: self._finish_loading(None, success=False, error_msg=str(e)))

    def _finish_loading(self, epher_file, success, error_msg=""):
        self.progress_bar.stop()
        self.apply_btn.config(state="normal")

        if success and epher_file:
            self.load_csv(epher_file)
        else:
            messagebox.showerror("Execution Error", f"Failed to generate/load epher.csv:\n{error_msg}")
            self.file_status_lbl.config(text="UPLINK FAILED // Check connection or parameters.", foreground="#fb7185")

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="Select NASA Ephemeris CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if path:
            self.load_csv(path)

    def load_csv(self, filepath):
        """Parses epher.csv including Earth ephemeris and real NASA LOLA terrain columns."""
        parsed_rows = []
        try:
            with open(filepath, mode="r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    raise ValueError("CSV file is empty.")

                header_map = {h.strip(): h for h in reader.fieldnames}
                required = {"datetime_str", "EL", "AZ"}
                if not required.issubset(header_map.keys()):
                    raise ValueError(f"CSV missing required headers. Found: {reader.fieldnames}")

                has_earth = {"Earth_EL", "Earth_AZ"}.issubset(header_map.keys())
                has_terrain = "Terrain_EL" in header_map
                has_earth_terrain = "Earth_Terrain_EL" in header_map
                has_elev = "Site_Elev_M" in header_map

                for i, raw_row in enumerate(reader):
                    dt_str = raw_row[header_map["datetime_str"]].strip()
                    el_val = float(raw_row[header_map["EL"]].strip())
                    az_val = float(raw_row[header_map["AZ"]].strip())

                    earth_el = float(raw_row[header_map["Earth_EL"]].strip()) if has_earth else None
                    earth_az = float(raw_row[header_map["Earth_AZ"]].strip()) if has_earth else None
                    terrain_el = float(raw_row[header_map["Terrain_EL"]].strip()) if has_terrain else None
                    earth_terrain_el = float(raw_row[header_map["Earth_Terrain_EL"]].strip()) if has_earth_terrain else terrain_el
                    site_elev = float(raw_row[header_map["Site_Elev_M"]].strip()) if has_elev else None

                    idx_key = header_map.get("", None)
                    row_idx = raw_row[idx_key].strip() if idx_key and raw_row[idx_key].strip() else str(i)

                    parsed_rows.append({
                        "index": row_idx,
                        "datetime_str": dt_str,
                        "EL": el_val,
                        "AZ": az_val,
                        "Earth_EL": earth_el,
                        "Earth_AZ": earth_az,
                        "Terrain_EL": terrain_el,
                        "Earth_Terrain_EL": earth_terrain_el,
                        "Site_Elev_M": site_elev
                    })
        except Exception as e:
            messagebox.showerror("CSV Load Error", f"Could not read CSV file:\n{e}")
            return

        if not parsed_rows:
            messagebox.showwarning("Empty Data", "No data rows were found in the selected CSV.")
            return

        self.csv_path = filepath
        self.rows = parsed_rows
        self.current_idx = 0

        elev_str = f" | Elev: {parsed_rows[0]['Site_Elev_M']:+.0f}m" if parsed_rows[0].get("Site_Elev_M") is not None else ""
        self.file_status_lbl.config(
            text=f"LOCKED // {len(self.rows)} epochs @ ({USER_X}°, {USER_Y}°){elev_str}",
            foreground="#34d399"
        )

        self.time_slider.config(from_=0, to=len(self.rows) - 1)
        self.slider_var.set(0)

        self._evaluate_landing_site()
        self._select_row(0)

    def _get_horizon_profile(self, query_az_deg):
        """
        Uses the exact 360° NASA LOLA horizon profile from 'horizon_360.csv' or the CSV's
        Terrain_EL points, falling back to procedural terrain only if no LOLA data exists.
        """
        h_file = os.path.join(os.getcwd(), "horizon_360.csv")
        if os.path.exists(h_file) and self.rows and self.rows[0].get("Terrain_EL") is not None:
            return get_terrain_horizon(query_az_deg, USER_Y, USER_X)

        if self.rows and self.rows[0].get("Terrain_EL") is not None:
            known_az = np.array([r["AZ"] % 360.0 for r in self.rows])
            known_el = np.array([r["Terrain_EL"] for r in self.rows])
            if self.rows[0].get("Earth_Terrain_EL") is not None:
                e_az = np.array([r["Earth_AZ"] % 360.0 for r in self.rows])
                e_el = np.array([r["Earth_Terrain_EL"] for r in self.rows])
                known_az = np.concatenate([known_az, e_az])
                known_el = np.concatenate([known_el, e_el])

            order = np.argsort(known_az)
            return np.interp(np.asarray(query_az_deg) % 360.0, known_az[order], known_el[order], period=360.0)

        return get_terrain_horizon(query_az_deg, USER_Y, USER_X)

    def _evaluate_landing_site(self):
        """Evaluates landing site suitability using Artemis-grade illumination, DTE comms, and eclipse limits."""
        el_values = [r["EL"] for r in self.rows]
        az_values = [r["AZ"] for r in self.rows]

        if self.rows[0].get("Terrain_EL") is not None:
            terrain_mask = np.array([r["Terrain_EL"] for r in self.rows])
        else:
            terrain_mask = self._get_horizon_profile(np.array(az_values))

        total_steps = len(el_values)
        sun_up_flags = [el > rim for el, rim in zip(el_values, terrain_mask)]
        sun_vis_pct = (sum(sun_up_flags) / total_steps) * 100.0
        max_el = max(el_values)

        # Determine time step duration in hours
        step_hours = 6.0
        if len(self.rows) >= 2:
            for fmt in ("%Y-%b-%d %H:%M", "%Y-%m-%d %H:%M"):
                try:
                    t0 = datetime.strptime(self.rows[0]["datetime_str"], fmt)
                    t1 = datetime.strptime(self.rows[1]["datetime_str"], fmt)
                    diff = abs((t1 - t0).total_seconds()) / 3600.0
                    if diff > 0:
                        step_hours = diff
                    break
                except ValueError:
                    continue

        # Longest continuous solar eclipse in hours
        max_blackout_steps = 0
        curr_streak = 0
        for is_lit in sun_up_flags:
            if not is_lit:
                curr_streak += 1
                max_blackout_steps = max(max_blackout_steps, curr_streak)
            else:
                curr_streak = 0
        max_eclipse_hrs = max_blackout_steps * step_hours

        has_earth = self.rows[0]["Earth_EL"] is not None
        if has_earth:
            e_el_values = [r["Earth_EL"] for r in self.rows]
            e_az_values = [r["Earth_AZ"] for r in self.rows]
            if self.rows[0].get("Earth_Terrain_EL") is not None:
                e_terrain_mask = np.array([r["Earth_Terrain_EL"] for r in self.rows])
            else:
                e_terrain_mask = self._get_horizon_profile(np.array(e_az_values))

            earth_up_flags = [el > rim for el, rim in zip(e_el_values, e_terrain_mask)]
            earth_vis_pct = (sum(earth_up_flags) / total_steps) * 100.0
            overlap_pct = (sum(1 for s, e in zip(sun_up_flags, earth_up_flags) if s and e) / total_steps) * 100.0

            self.verdict_stats_lbl.config(
                text=f"SUN: {sun_vis_pct:.0f}% | DTE: {earth_vis_pct:.0f}% | MAX DARK: {max_eclipse_hrs:.0f}h"
            )
        else:
            earth_vis_pct = 100.0
            overlap_pct = sun_vis_pct
            self.verdict_stats_lbl.config(
                text=f"SUN VIS: {sun_vis_pct:.1f}% | MAX ECLIPSE: {max_eclipse_hrs:.0f} hrs"
            )

        elev_m = self.rows[0].get("Site_Elev_M")
        elev_note = f" (LOLA Elev: {elev_m:+.0f}m)" if elev_m is not None else ""

        if sun_vis_pct >= 70.0 and earth_vis_pct >= 65.0 and max_eclipse_hrs <= 125.0:
            self.verdict_badge_lbl.config(text="★ OPTIMAL (ARTEMIS-GRADE SITE)", foreground="#34d399")
            description = (
                f"PASS{elev_note}: Solar illumination ({sun_vis_pct:.1f}%) and Direct-to-Earth comms ({earth_vis_pct:.1f}%) "
                f"exceed mission thresholds, with {overlap_pct:.1f}% simultaneous power + telemetry overlap. "
                f"Longest continuous shadow is {max_eclipse_hrs:.0f} hrs—within 96-hr lander battery limits."
            )
        elif sun_vis_pct >= 40.0 and earth_vis_pct >= 35.0 and max_eclipse_hrs <= 168.0:
            self.verdict_badge_lbl.config(text="▲ CONDITIONAL (BATTERY / RELAY REQ)", foreground="#fbbf24")
            description = (
                f"CAUTION{elev_note}: Site achieves {sun_vis_pct:.1f}% sunlight and {earth_vis_pct:.1f}% Earth DTE visibility "
                f"(peak solar angle {max_el:+.1f}°), but experiences a continuous {max_eclipse_hrs:.0f}-hr shadow. "
                f"Viable for landers with extended hibernation batteries or orbital relay support."
            )
        else:
            self.verdict_badge_lbl.config(text="✖ UNSUITABLE (CRITICAL BLACKOUT)", foreground="#fb7185")
            description = (
                f"FAIL{elev_note}: High terrain occlusion limits sunlight to {sun_vis_pct:.1f}% and Earth DTE to {earth_vis_pct:.1f}%, "
                f"with a {max_eclipse_hrs:.0f}-hr continuous eclipse exceeding standard thermal/battery survival limits. "
                f"Recommend shifting target coordinates toward an elevated crater rim."
            )

        self.verdict_desc_lbl.config(text=description)

    def _create_sample_csv(self):
        """Generates a sample 'epher.csv' with both Sun and Earth columns for offline testing."""
        sample_path = os.path.join(os.getcwd(), "epher.csv")
        # Remove stale horizon_360.csv if generating offline sample data
        h_file = os.path.join(os.getcwd(), "horizon_360.csv")
        if os.path.exists(h_file):
            try:
                os.remove(h_file)
            except Exception:
                pass

        try:
            start = datetime.strptime(self.start_var.get().strip(), "%Y-%m-%d")
        except ValueError:
            start = datetime(2026, 11, 14, 0, 0)

        with open(sample_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["", "datetime_str", " EL", " AZ", "Earth_EL", "Earth_AZ"])
            for step in range(120):
                dt = start + timedelta(hours=step * 6)
                sun_az = (step * 3.05) % 360.0
                sun_el = 1.55 * math.sin(step * 0.055) + 0.45
                earth_az = (355.0 + 7.2 * math.sin(step * 0.06)) % 360.0
                earth_el = 4.8 + 6.1 * math.cos(step * 0.062)
                writer.writerow([
                    step, dt.strftime("%Y-%m-%d %H:%M"),
                    f"{sun_el:.4f}", f"{sun_az:.4f}",
                    f"{earth_el:.4f}", f"{earth_az:.4f}"
                ])
        self.load_csv(sample_path)

    # =========================================================================
    # UI INTERACTION & RENDERING
    # =========================================================================
    def _on_slider_move(self, val):
        if not self.rows:
            return
        idx = int(float(val))
        self._select_row(idx)

    def _az_to_cardinal(self, az):
        dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        ix = int(round(az / 22.5)) % 16
        return dirs[ix]

    def _select_row(self, idx):
        self.current_idx = idx
        row = self.rows[idx]

        el = row["EL"]
        az = row["AZ"]
        sun_rim = row["Terrain_EL"] if row.get("Terrain_EL") is not None else float(self._get_horizon_profile(az))
        sun_up = el > sun_rim

        self.dt_display_lbl.config(text=f"UTC EPOCH: {row['datetime_str']}")
        self.el_val_lbl.config(text=f"{el:+.2f}°")
        self.horizon_status_lbl.config(
            text=f"{'ILLUMINATED' if sun_up else 'ECLIPSED'} | {az:.0f}° {self._az_to_cardinal(az)}",
            foreground="#34d399" if sun_up else "#fb7185"
        )

        if row["Earth_EL"] is not None:
            e_el = row["Earth_EL"]
            e_az = row["Earth_AZ"]
            earth_rim = row["Earth_Terrain_EL"] if row.get("Earth_Terrain_EL") is not None else float(self._get_horizon_profile(e_az))
            earth_up = e_el > earth_rim
            self.earth_el_lbl.config(text=f"{e_el:+.2f}°")
            self.earth_status_lbl.config(
                text=f"{'DTE ONLINE' if earth_up else 'OCCLUDED'} | {e_az:.0f}° {self._az_to_cardinal(e_az)}",
                foreground="#34d399" if earth_up else "#fb7185"
            )
        else:
            self.earth_el_lbl.config(text="N/A")
            self.earth_status_lbl.config(text="No Earth Telemetry", foreground="#64748b")

        self._render_charts()

    def _draw_empty_charts(self):
        self.ax_sky.clear()
        self.ax_sky.set_title("360° LOCAL TERRAIN HORIZON & SKY-DOME (SUN & EARTH)", color="#38bdf8", fontsize=9.5, fontweight="bold", loc="left")
        self.ax_sky.text(0.5, 0.5, "AWAITING COORDINATE UPLINK // ENTER TARGET & CLICK ACQUIRE", color="#475569", fontfamily="monospace", ha="center", va="center", transform=self.ax_sky.transAxes)
        self.ax_sky.grid(True, color="#0f1b33", linestyle="--", linewidth=0.6)

        self.ax_timeline.clear()
        self.ax_timeline.set_title("SOLAR & EARTH ELEVATION PROFILE (SHADED = TERRAIN ECLIPSE)", color="#38bdf8", fontsize=9.5, fontweight="bold", loc="left")
        self.ax_timeline.grid(True, color="#0f1b33", linestyle="--", linewidth=0.6)
        self.canvas.draw_idle()

    def _render_charts(self):
        az_all = np.array([r["AZ"] for r in self.rows])
        el_all = np.array([r["EL"] for r in self.rows])
        cur_row = self.rows[self.current_idx]
        is_polar = abs(USER_Y) > 75.0

        has_earth = cur_row["Earth_EL"] is not None
        if has_earth:
            e_az_all = np.array([r["Earth_AZ"] for r in self.rows])
            e_el_all = np.array([r["Earth_EL"] for r in self.rows])

        # =====================================================================
        # SUBPLOT 1: 360° SKY-DOME & REAL LOLA TERRAIN HORIZON
        # =====================================================================
        self.ax_sky.clear()
        self.ax_sky.set_facecolor("#040711")

        az_grid = np.linspace(0, 360, 361)
        terrain_el = self._get_horizon_profile(az_grid)

        all_els = np.concatenate([el_all, e_el_all, terrain_el]) if has_earth else np.concatenate([el_all, terrain_el])
        min_el = min(float(np.min(all_els)) - 1.5, -6.0 if is_polar else -25.0)
        max_el = max(float(np.max(all_els)) + 2.5, 14.0 if is_polar else 75.0)

        self.ax_sky.set_xlim(0, 360)
        self.ax_sky.set_ylim(min_el, max_el)
        self.ax_sky.set_xticks([0, 90, 180, 270, 360])
        self.ax_sky.set_xticklabels(["N (0°)", "E (90°)", "S (180°)", "W (270°)", "N (360°)"], color="#7dd3fc", fontsize=8, fontfamily="monospace")
        self.ax_sky.tick_params(axis="y", colors="#7dd3fc", labelsize=8)
        self.ax_sky.set_ylabel("ELEVATION (°)", color="#7dd3fc", fontsize=8, fontfamily="monospace")

        data_source_tag = "NASA LOLA DEM" if cur_row.get("Terrain_EL") is not None else "SYNTHETIC PROFILE"
        self.ax_sky.set_title(
            f"360° TERRAIN HORIZON & SKY-DOME // SITE ({USER_X}°, {USER_Y}°) [{data_source_tag}]",
            color="#f8fafc", fontsize=9.5, fontweight="bold", fontfamily="monospace", loc="left"
        )
        self.ax_sky.grid(True, color="#0f1b33", linestyle="--", linewidth=0.6)

        # Deep-space starfield in the upper sky
        rng = np.random.default_rng(42)
        star_x = rng.uniform(0, 360, 85)
        star_y = rng.uniform(max(0, min_el * 0.2), max_el, 85)
        self.ax_sky.scatter(star_x, star_y, s=rng.uniform(1, 4, 85), color="#e0f2fe", alpha=0.40, zorder=1)

        # 0° Geometric Horizon line
        self.ax_sky.axhline(0, color="#38bdf8", linestyle=":", linewidth=0.9, alpha=0.45, zorder=2)

        # Pulsing Halo Multiplier
        pulse = 1.0 + 0.28 * math.sin(self.pulse_phase)

        # Sun Trajectory Ribbon & Pulsing Beacon
        self.ax_sky.scatter(az_all, el_all, s=6, color="#fbbf24", alpha=0.35, label="Sun Path", zorder=3)
        self.ax_sky.scatter([cur_row["AZ"]], [cur_row["EL"]], s=480 * pulse, color="#f59e0b", alpha=0.16, zorder=4)
        self.ax_sky.scatter([cur_row["AZ"]], [cur_row["EL"]], s=140, color="#fef08a", edgecolors="#f59e0b", linewidths=2, zorder=4)

        # Earth Libration Trail & Pulsing Beacon
        if has_earth:
            self.ax_sky.scatter(e_az_all, e_el_all, s=7, color="#38bdf8", alpha=0.45, label="Earth Libration", zorder=3)
            self.ax_sky.scatter([cur_row["Earth_AZ"]], [cur_row["Earth_EL"]], s=400 * pulse, color="#0ea5e9", alpha=0.18, zorder=4)
            self.ax_sky.scatter([cur_row["Earth_AZ"]], [cur_row["Earth_EL"]], s=110, color="#38bdf8", edgecolors="#e0f2fe", linewidths=1.5, zorder=4)

        # Translucent Frosted Crater-Rim Terrain Silhouette
        self.ax_sky.fill_between(az_grid, min_el, terrain_el, color="#0c192e", alpha=0.72, zorder=5)
        self.ax_sky.plot(az_grid, terrain_el, color="#38bdf8", linewidth=2.8, alpha=0.22, zorder=6)
        self.ax_sky.plot(az_grid, terrain_el, color="#7dd3fc", linewidth=1.1, alpha=0.85, zorder=6, label="LOLA Horizon")

        # Floating HUD Callout Badges
        self.ax_sky.annotate(
            f"☀ SUN [{cur_row['EL']:+.1f}°]",
            (cur_row["AZ"], cur_row["EL"]),
            xytext=(10, 6), textcoords="offset points",
            color="#fde047", fontsize=8, fontweight="bold", fontfamily="monospace", zorder=7
        )
        if has_earth:
            self.ax_sky.annotate(
                f"🌍 EARTH [{cur_row['Earth_EL']:+.1f}°]",
                (cur_row["Earth_AZ"], cur_row["Earth_EL"]),
                xytext=(10, 6), textcoords="offset points",
                color="#7dd3fc", fontsize=8, fontweight="bold", fontfamily="monospace", zorder=7
            )

        # =====================================================================
        # SUBPLOT 2: SOLAR & EARTH ELEVATION TIMELINE
        # =====================================================================
        self.ax_timeline.clear()
        self.ax_timeline.set_facecolor("#040711")

        indices = np.arange(len(self.rows))
        t_min = min(float(np.min(all_els)) - 1.5, -6.0 if is_polar else -70.0)
        t_max = max(float(np.max(all_els)) + 2.0, 10.0 if is_polar else 75.0)

        self.ax_timeline.set_xlim(0, max(1, len(self.rows) - 1))
        self.ax_timeline.set_ylim(t_min, t_max)
        self.ax_timeline.tick_params(colors="#7dd3fc", labelsize=8)
        self.ax_timeline.set_ylabel("ELEVATION (°)", color="#7dd3fc", fontsize=8, fontfamily="monospace")
        self.ax_timeline.set_title(
            f"SOLAR & EARTH ELEVATION PROFILE // {cur_row['datetime_str']}",
            color="#f8fafc", fontsize=9.5, fontweight="bold", fontfamily="monospace", loc="left"
        )
        self.ax_timeline.grid(True, color="#0f1b33", linestyle="--", linewidth=0.6)
        self.ax_timeline.axhline(0, color="#64748b", linestyle=":", linewidth=0.8)

        if cur_row.get("Terrain_EL") is not None:
            terrain_along_path = np.array([r["Terrain_EL"] for r in self.rows])
        else:
            terrain_along_path = self._get_horizon_profile(az_all)

        is_occluded = el_all <= terrain_along_path

        self.ax_timeline.fill_between(
            indices, t_min, t_max,
            where=is_occluded, color="#f43f5e", alpha=0.12
        )

        # Translucent area glow beneath Sun & Earth curves
        self.ax_timeline.plot(indices, terrain_along_path, color="#64748b", linestyle="--", linewidth=0.9, label="Terrain Mask")
        self.ax_timeline.plot(indices, el_all, color="#fbbf24", linewidth=1.8, label="Sun Elevation")
        self.ax_timeline.fill_between(indices, t_min, el_all, color="#fbbf24", alpha=0.06)

        if has_earth:
            self.ax_timeline.plot(indices, e_el_all, color="#38bdf8", linewidth=1.8, label="Earth Elevation")
            self.ax_timeline.fill_between(indices, t_min, e_el_all, color="#38bdf8", alpha=0.06)

        self.ax_timeline.axvline(self.current_idx, color="#38bdf8", linewidth=3.5, alpha=0.22)
        self.ax_timeline.axvline(self.current_idx, color="#ffffff", linewidth=1.3)

        tick_count = min(6, len(self.rows))
        if tick_count > 1:
            tick_positions = [int(i * (len(self.rows) - 1) / (tick_count - 1)) for i in range(tick_count)]
            self.ax_timeline.set_xticks(tick_positions)
            self.ax_timeline.set_xticklabels([self.rows[p]["datetime_str"] for p in tick_positions], rotation=12, ha="right", fontsize=7.5, fontfamily="monospace")

        leg = self.ax_timeline.legend(loc="upper right", facecolor="#070c18", edgecolor="#1e3a5f", labelcolor="#e2e8f0", fontsize=7.5, ncol=3)
        leg.get_frame().set_alpha(0.75)

        self.canvas.draw_idle()


if __name__ == "__main__":
    app = LunarCSVViewerApp()
    app.mainloop()