"""Card Unloader — Settings (macOS)."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
# The standalone app is one single .app bundle, built with PyInstaller in
# --onefile mode and wrapped into a Finder-launchable bundle:
# "Card Unloader.app/Contents/MacOS/Card Unloader". Finder double-clicks run
# it directly, and it unpacks itself to a temp folder on each launch, so
# there is no supporting folder to keep beside it. A pick-folder dialog asks
# where to put the bundle after each build (default: right next to
# config_ui.py).
APP_NAME = "Card Unloader.app"
APP_PATH = SCRIPT_DIR / APP_NAME  # default save location (if the picker is cancelled)
BUILT_APP = SCRIPT_DIR / "dist" / APP_NAME  # where the bundle is first assembled
ENTRY_NAME = "Card Unloader"  # bundle folder minus .app must match this

DEFAULT_CONFIG = {
    "extensions": ["CR2", "CR3", "NEF", "RAF", "ARW", "DNG", "JPG", "JPEG"],
    "primary_destination": "",
    "backup_destination": "",
    "lightroom_path": "",
}

# Adobe installs its apps as "<name>.app" folders under a per-product folder
# in /Applications, e.g. "Adobe Lightroom CC/Adobe Lightroom.app". Classic's
# real bundle is preferred when several match.
LIGHTROOM_GLOBS = [
    "/Applications/Adobe Lightroom Classic*/*.app",
    "/Applications/Adobe Lightroom*/*.app",
    "/Applications/*Lightroom*.app",
]


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _is_app_bundle(p):
    """True for a Finder-launchable .app bundle (folder with Contents/MacOS)."""
    return Path(p).suffix == ".app" and (Path(p) / "Contents" / "MacOS").is_dir()


def find_lightroom():
    seen = []
    for pattern in LIGHTROOM_GLOBS:
        for p in sorted(glob.glob(pattern)):
            if p not in seen:
                seen.append(p)
    for p in seen:
        if _is_app_bundle(p) and "classic" in p.lower():
            return p
    for p in seen:
        if _is_app_bundle(p):
            return p
    return None


def build_app(save_dir):
    """Build a standalone 'Card Unloader.app' bundle and save it under save_dir.

    --onefile + --windowed: everything (the app, its libraries, config.json)
    is packed into one binary, and PyInstaller itself assembles a Finder-
    launchable Card Unloader.app bundle (with a minimal Info.plist) in dist/.
    The bundle is copied to save_dir/Card Unloader.app wherever the user
    chose; if PyInstaller only produced the bare binary, we wrap it.
    Returns (True, bundle_path) on success, (False, error_text) on failure.
    """
    save_dir = Path(save_dir)
    script = SCRIPT_DIR / "card_unloader.py"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", ENTRY_NAME,
        # Absolute path — PyInstaller resolves relative --add-data against the
        # .spec directory, which we put in build/, not the project root.
        f"--add-data={SCRIPT_DIR / 'config.json'}{os.pathsep}.",
        "--distpath", str(SCRIPT_DIR / "dist"),
        "--workpath", str(SCRIPT_DIR / "build"),
        "--specpath", str(SCRIPT_DIR / "build"),
        str(script),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
    if r.returncode != 0:
        return False, r.stderr.strip()[-2000:] or f"PyInstaller exit code {r.returncode}"
    # With --windowed PyInstaller assembles the Finder-launchable bundle itself
    # (dist/Card Unloader.app with a minimal Info.plist). If the bundle isn't
    # there but the bare binary is, wrap it ourselves — same layout, Finder
    # launches both (executable basename must equal the folder minus .app).
    built = SCRIPT_DIR / "dist" / ENTRY_NAME
    bundle = SCRIPT_DIR / "dist" / APP_NAME
    entry = bundle / "Contents" / "MacOS" / ENTRY_NAME
    if not entry.is_file():
        if not built.is_file():
            return False, f"Build reported success but {built} was not produced."
        try:
            macos_dir = bundle / "Contents" / "MacOS"
            macos_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(built), str(entry))
            entry.chmod(0o755)
        except OSError as e:
            return False, f"Built the binary but couldn't assemble the bundle: {e}"

    # Copy the bundle to the chosen folder, replacing anything already there.
    target = save_dir / APP_NAME
    try:
        if os.path.realpath(target) != os.path.realpath(bundle):
            shutil.copytree(str(bundle), str(target), dirs_exist_ok=True)
        shutil.rmtree(SCRIPT_DIR / "dist", ignore_errors=True)
    except OSError as e:
        return False, f"Built the app but couldn't save it to {target}: {e}"
    if not (target / "Contents" / "MacOS" / ENTRY_NAME).is_file():
        return False, f"Build reported success but {target} was not produced."
    return True, str(target)


class ConfigApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Card Unloader Settings")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        self.cfg = load_config()
        self._build()

        # Centre on screen
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"+{x}+{y}")

    def _build(self):
        root = self.root

        ttk.Label(
            root, text="Card Unloader Settings",
            font=("Helvetica", 14, "bold"),
        ).pack(pady=(14, 8), anchor="w", padx=12)

        # --- Extensions ---
        ttk.Label(root, text="File extensions  (comma-separated, no dots):").pack(
            fill="x", padx=12, pady=(10, 0), anchor="w"
        )
        self.ext_var = tk.StringVar()
        self.ext_var.set(", ".join(self.cfg.get("extensions", DEFAULT_CONFIG["extensions"])))
        ttk.Entry(root, textvariable=self.ext_var).pack(fill="x", padx=12)

        # --- Primary destination ---
        ttk.Label(root, text="Primary destination:").pack(
            fill="x", padx=12, pady=(14, 0), anchor="w"
        )
        pf = ttk.Frame(root); pf.pack(fill="x", padx=12)
        self.prim_var = tk.StringVar()
        self.prim_var.set(self.cfg.get("primary_destination", ""))
        ttk.Entry(pf, textvariable=self.prim_var).pack(side="left", fill="x", expand=True)
        ttk.Button(pf, text="Browse…", command=self._browse_primary, width=10).pack(side="left", padx=(6, 0))

        # --- Backup destination ---
        ttk.Label(root, text="Backup destination:").pack(
            fill="x", padx=12, pady=(14, 0), anchor="w"
        )
        bf = ttk.Frame(root); bf.pack(fill="x", padx=12)
        self.bak_var = tk.StringVar()
        self.bak_var.set(self.cfg.get("backup_destination", ""))
        ttk.Entry(bf, textvariable=self.bak_var).pack(side="left", fill="x", expand=True)
        ttk.Button(bf, text="Browse…", command=self._browse_backup, width=10).pack(side="left", padx=(6, 0))

        # --- Lightroom path ---
        ttk.Label(root, text="Lightroom app:").pack(
            fill="x", padx=12, pady=(14, 0), anchor="w"
        )
        lf = ttk.Frame(root); lf.pack(fill="x", padx=12)
        self.lr_var = tk.StringVar()
        self.lr_var.set(self.cfg.get("lightroom_path", ""))
        ttk.Entry(lf, textvariable=self.lr_var).pack(side="left", fill="x", expand=True)
        ttk.Button(lf, text="Browse…", command=self._browse_lr, width=10).pack(side="left", padx=(6, 0))
        ttk.Button(lf, text="Find", command=self._find_lr, width=6).pack(side="left", padx=(2, 0))

        # --- Action buttons ---
        btns = ttk.Frame(root); btns.pack(pady=20)
        ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=5)
        ttk.Button(btns, text="Build Standalone App", command=self._build_app_btn).pack(side="left", padx=5)

    # --- Browse handlers ---

    def _browse_primary(self):
        p = filedialog.askdirectory(title="Primary destination folder", parent=self.root)
        if p:
            self.prim_var.set(p)

    def _browse_backup(self):
        p = filedialog.askdirectory(title="Backup folder", parent=self.root)
        if p:
            self.bak_var.set(p)

    def _browse_lr(self):
        # .app is a folder on macOS; pick it directly (or drill into
        # Contents/MacOS and pick the executable inside — both are supported).
        p = filedialog.askdirectory(title="Select the Adobe Lightroom .app folder", parent=self.root)
        if p:
            self.lr_var.set(p)

    def _find_lr(self):
        found = find_lightroom()
        if found:
            self.lr_var.set(found)
        else:
            messagebox.showinfo(
                "Find Lightroom",
                "Lightroom not found in /Applications.\n"
                "Use Browse to locate it manually.",
                parent=self.root,
            )

    # --- Actions ---

    def _collect_cfg(self):
        """Read the current entry fields into a config dict (no dialogs)."""
        ext_str = self.ext_var.get().strip()
        exts = [e.strip().upper().lstrip(".") for e in ext_str.split(",") if e.strip()]
        return {
            "extensions": exts,
            "primary_destination": self.prim_var.get().strip(),
            "backup_destination": self.bak_var.get().strip(),
            "lightroom_path": self.lr_var.get().strip(),
        }

    def _save(self):
        cfg = self._collect_cfg()
        if not cfg["extensions"]:
            messagebox.showwarning(
                "Settings", "Enter at least one file extension.", parent=self.root
            )
            return

        save_config(cfg)

        warnings = []
        if not cfg["primary_destination"]:
            warnings.append("Primary destination is empty.")
        elif not os.path.isdir(cfg["primary_destination"]):
            warnings.append(f"Primary destination doesn't exist:\n{cfg['primary_destination']}")
        if cfg["backup_destination"] and not os.path.isdir(cfg["backup_destination"]):
            warnings.append(f"Backup destination doesn't exist:\n{cfg['backup_destination']}")
        if cfg["lightroom_path"]:
            p = Path(cfg["lightroom_path"])
            ok = _is_app_bundle(cfg["lightroom_path"]) or (
                p.is_file() and os.access(p, os.X_OK)
            )
            if not ok:
                warnings.append(f"Lightroom not found:\n{cfg['lightroom_path']}")

        if warnings:
            messagebox.showwarning(
                "Settings saved",
                "Saved, but please check:\n\n" + "\n".join("• " + w for w in warnings),
                parent=self.root,
            )
        else:
            messagebox.showinfo("Settings", "Settings saved!", parent=self.root)

    def _build_app_btn(self):
        cfg = self._collect_cfg()
        if not cfg["extensions"]:
            messagebox.showwarning(
                "Build Standalone App",
                "Enter at least one file extension first.",
                parent=self.root,
            )
            return
        # Embed the latest settings into the app.
        save_config(cfg)

        try:
            import PyInstaller  # noqa: F401
        except ImportError:
            if not messagebox.askyesno(
                "Build Standalone App",
                "PyInstaller isn't installed.\n\nInstall it now?\n(runs: pip install pyinstaller)",
                parent=self.root,
            ):
                return
            p = subprocess.run(
                [sys.executable, "-m", "pip", "install", "pyinstaller"],
                capture_output=True, text=True,
            )
            if p.returncode != 0:
                messagebox.showerror(
                    "Build Standalone App",
                    f"pip install failed:\n\n{p.stderr.strip()[-1500:] or 'unknown error'}",
                    parent=self.root,
                )
                return

        # Ask which folder to put Card Unloader.app in. Cancelling falls back
        # to the project folder next to config_ui.py.
        save_dir = filedialog.askdirectory(
            title="Choose a folder for Card Unloader.app",
            initialdir=str(SCRIPT_DIR),
            parent=self.root,
        )
        if not save_dir:
            save_dir = str(SCRIPT_DIR)

        messagebox.showinfo(
            "Build Standalone App",
            "Building a standalone app…\nThis can take a minute.\n\n"
            f"It will be saved as:\n{Path(save_dir) / APP_NAME}",
            parent=self.root,
        )
        ok, info = build_app(save_dir)
        if ok:
            messagebox.showinfo(
                "Build Standalone App",
                f"Done.\n\nStandalone app:\n{info}\n\n"
                "Drag it anywhere (Desktop, dock…) and double-click it in Finder.",
                parent=self.root,
            )
        else:
            messagebox.showerror("Build Standalone App", f"Build failed:\n\n{info}", parent=self.root)


def main():
    root = tk.Tk()
    ConfigApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
