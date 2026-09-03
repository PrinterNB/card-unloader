"""Card Unloader — Settings."""
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
# The standalone app is one single exe, built with PyInstaller in --onefile
# mode. Everything (the app, its libraries, config.json) is packed inside the
# one exe; it unpacks itself to a temp folder each time it runs, so there is
# no _internal folder to keep beside it. A save-as dialog asks where to put
# the exe after each build (default: right next to config_ui.pyw).
EXE_NAME = "Card Unloader.exe"
EXE_PATH = SCRIPT_DIR / EXE_NAME  # default save location (if the picker is cancelled)
BUILT_EXE = SCRIPT_DIR / "dist" / EXE_NAME  # where PyInstaller first builds it

DEFAULT_CONFIG = {
    "extensions": ["CR2", "CR3", "NEF", "RAF", "ARW", "DNG", "JPG", "JPEG"],
    "primary_destination": "",
    "backup_destination": "",
    "lightroom_path": r"C:\Program Files\Adobe\Adobe Lightroom CC\lightroom.exe",
}

LIGHTROOM_LOCATIONS = [
    r"C:\Program Files\Adobe\Adobe Lightroom CC\lightroom.exe",
    r"C:\Program Files\Adobe\Adobe Lightroom Classic\Lightroom.exe",
    r"C:\Program Files\Adobe\Lightroom\Lightroom.exe",
    r"C:\Program Files (x86)\Adobe\Adobe Lightroom CC\lightroom.exe",
    r"C:\Program Files (x86)\Adobe\Adobe Lightroom Classic\Lightroom.exe",
    r"C:\Program Files (x86)\Adobe\Lightroom\Lightroom.exe",
]


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def find_lightroom():
    for p in LIGHTROOM_LOCATIONS:
        if os.path.isfile(p):
            return p
    return None


def build_exe(save_path):
    """Build a standalone 'Card Unloader' exe and save it at save_path.

    --onefile mode: everything (the app, its libraries, config.json) is
    packed into a single Card Unloader.exe. On each launch it unpacks itself
    to a temp folder, so there's no _internal folder to keep beside it.
    PyInstaller builds into dist/, and the one exe is copied to save_path
    wherever the user chose.
    Returns (True, exe_path) on success, (False, error_text) on failure.
    """
    save_path = Path(save_path)
    pyw = SCRIPT_DIR / "card_unloader.pyw"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", "Card Unloader",
        # Absolute path — PyInstaller resolves relative --add-data against the
        # .spec directory, which we put in build/, not the project root.
        f"--add-data={SCRIPT_DIR / 'config.json'}{os.pathsep}.",
        "--distpath", str(SCRIPT_DIR / "dist"),
        "--workpath", str(SCRIPT_DIR / "build"),
        "--specpath", str(SCRIPT_DIR / "build"),
        str(pyw),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
    if r.returncode != 0:
        return False, r.stderr.strip()[-2000:] or f"PyInstaller exit code {r.returncode}"
    if not BUILT_EXE.exists():
        return False, f"Build reported success but {BUILT_EXE} was not produced."

    # Copy the one exe to the chosen path, replacing anything already there.
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(BUILT_EXE), str(save_path))
    except OSError as e:
        return False, f"Built the exe but couldn't save it to {save_path}: {e}"
    shutil.rmtree(SCRIPT_DIR / "dist", ignore_errors=True)
    if not save_path.exists():
        return False, f"Build reported success but {save_path} was not produced."
    return True, str(save_path)


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
            font=("Segoe UI", 14, "bold"),
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
        ttk.Button(pf, text="Browse\u2026", command=self._browse_primary, width=10).pack(side="left", padx=(6, 0))

        # --- Backup destination ---
        ttk.Label(root, text="Backup destination:").pack(
            fill="x", padx=12, pady=(14, 0), anchor="w"
        )
        bf = ttk.Frame(root); bf.pack(fill="x", padx=12)
        self.bak_var = tk.StringVar()
        self.bak_var.set(self.cfg.get("backup_destination", ""))
        ttk.Entry(bf, textvariable=self.bak_var).pack(side="left", fill="x", expand=True)
        ttk.Button(bf, text="Browse\u2026", command=self._browse_backup, width=10).pack(side="left", padx=(6, 0))

        # --- Lightroom path ---
        ttk.Label(root, text="Lightroom executable:").pack(
            fill="x", padx=12, pady=(14, 0), anchor="w"
        )
        lf = ttk.Frame(root); lf.pack(fill="x", padx=12)
        self.lr_var = tk.StringVar()
        self.lr_var.set(self.cfg.get("lightroom_path", ""))
        ttk.Entry(lf, textvariable=self.lr_var).pack(side="left", fill="x", expand=True)
        ttk.Button(lf, text="Browse\u2026", command=self._browse_lr, width=10).pack(side="left", padx=(6, 0))
        ttk.Button(lf, text="Find", command=self._find_lr, width=6).pack(side="left", padx=(2, 0))

        # --- Action buttons ---
        btns = ttk.Frame(root); btns.pack(pady=20)
        ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=5)
        ttk.Button(btns, text="Build Standalone EXE", command=self._build_exe).pack(side="left", padx=5)

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
        p = filedialog.askopenfilename(
            title="Select Lightroom.exe", parent=self.root,
            filetypes=[("Executables", "*.exe")],
        )
        if p:
            self.lr_var.set(p)

    def _find_lr(self):
        found = find_lightroom()
        if found:
            self.lr_var.set(found)
        else:
            messagebox.showinfo(
                "Find Lightroom",
                "Lightroom not found in common locations.\n"
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
        if cfg["lightroom_path"] and not os.path.isfile(cfg["lightroom_path"]):
            warnings.append(f"Lightroom not found:\n{cfg['lightroom_path']}")

        if warnings:
            messagebox.showwarning(
                "Settings saved",
                "Saved, but please check:\n\n" + "\n".join("\u2022 " + w for w in warnings),
                parent=self.root,
            )
        else:
            messagebox.showinfo("Settings", "Settings saved!", parent=self.root)

    def _build_exe(self):
        cfg = self._collect_cfg()
        if not cfg["extensions"]:
            messagebox.showwarning(
                "Build Standalone EXE",
                "Enter at least one file extension first.",
                parent=self.root,
            )
            return
        # Embed the latest settings into the exe.
        save_config(cfg)

        try:
            import PyInstaller  # noqa: F401
        except ImportError:
            if not messagebox.askyesno(
                "Build Standalone EXE",
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
                    "Build Standalone EXE",
                    f"pip install failed:\n\n{p.stderr.strip()[-1500:] or 'unknown error'}",
                    parent=self.root,
                )
                return

        # Ask where to save the single exe. Cancelling falls back to the
        # project folder next to config_ui.pyw.
        save_path = filedialog.asksaveasfilename(
            title="Where should Card Unloader.exe be saved?",
            initialfile=str(EXE_PATH),
            defaultextension=".exe",
            filetypes=[("Executable", "*.exe")],
            parent=self.root,
        )
        if not save_path:
            save_path = EXE_PATH
        save_path = Path(save_path)

        messagebox.showinfo(
            "Build Standalone EXE",
            "Building a standalone exe\u2026\nThis can take a minute.\n\n"
            f"It will be saved as:\n{save_path}",
            parent=self.root,
        )
        ok, info = build_exe(save_path)
        if ok:
            messagebox.showinfo(
                "Build Standalone EXE",
                f"Done.\n\nStandalone app:\n{info}\n\n"
                "It's a single file \u2014 copy it anywhere you like.",
                parent=self.root,
            )
        else:
            messagebox.showerror("Build Standalone EXE", f"Build failed:\n\n{info}", parent=self.root)


def main():
    root = tk.Tk()
    ConfigApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
