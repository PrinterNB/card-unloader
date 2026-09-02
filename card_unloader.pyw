"""Card Unloader — one-click SD card photo unloader."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from string import ascii_uppercase
import tkinter as tk
from tkinter import messagebox

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built exe; config.json is embedded and extracted here.
    BASE_DIR = Path(getattr(sys, "_MEIPASS"))
else:
    BASE_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = BASE_DIR
CONFIG_FILE = BASE_DIR / "config.json"


def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_removable_drives():
    """Return drive root paths (e.g. ['E:\\', 'F:\\']) for all removable drives."""
    results = []
    for letter in ascii_uppercase:
        path = f"{letter}:\\"
        if os.path.exists(path):
            if ctypes.windll.kernel32.GetDriveTypeW(path) == 2:  # DRIVE_REMOVABLE
                results.append(path)
    return results


def unique_dest(dest_dir, filename):
    """Return a non-colliding path in dest_dir for the given filename."""
    p = Path(dest_dir) / filename
    stem, ext = p.stem, p.suffix
    counter = 1
    while p.exists():
        p = Path(dest_dir) / f"{stem} ({counter}){ext}"
        counter += 1
    return p


def pick_drive(root, drives):
    """Toplevel dialog to pick which card to unload. Returns path or None."""
    dialog = tk.Toplevel(root)
    dialog.title("Select Camera Card")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    tk.Label(dialog, text="Multiple cards detected. Select one:").pack(pady=(10, 5))
    lb = tk.Listbox(dialog, height=min(len(drives), 8), width=40)
    for d in drives:
        lb.insert(tk.END, d)
    lb.selection_set(0)
    lb.pack(pady=5)
    result = [None]

    def on_ok():
        sel = lb.curselection()
        if sel:
            result[0] = drives[sel[0]]
        dialog.destroy()

    tk.Button(dialog, text="Unload", command=on_ok).pack(pady=5)
    dialog.grab_set()
    dialog.wait_window()
    return result[0]


def run_unload(root):
    config = load_config()
    if config is None:
        messagebox.showerror(
            "Card Unloader",
            "Configuration not found.\n\n"
            "Open \u201cCard Unloader Settings\u201d to set up your folders first.",
            parent=root,
        )
        return

    extensions = {e.upper().lstrip(".") for e in config.get("extensions", [])}
    primary_dest = config.get("primary_destination", "").strip()
    backup_dest = config.get("backup_destination", "").strip()
    lightroom = config.get("lightroom_path", "").strip()

    if not primary_dest:
        messagebox.showerror(
            "Card Unloader",
            "Primary destination is not set.\n\n"
            "Open \u201cCard Unloader Settings\u201d to configure.",
            parent=root,
        )
        return

    if not os.path.isdir(primary_dest):
        messagebox.showerror(
            "Card Unloader",
            f"Primary destination not found:\n{primary_dest}\n\n"
            "Open \u201cCard Unloader Settings\u201d to fix this.",
            parent=root,
        )
        return

    # --- Detect camera card ---
    drives = find_removable_drives()
    if not drives:
        messagebox.showerror(
            "Card Unloader",
            "No camera card detected.\n\nInsert your card and try again.",
            parent=root,
        )
        return

    if len(drives) == 1:
        card_path = drives[0]
    else:
        card_path = pick_drive(root, drives)
        if card_path is None:
            return
    card_path = card_path.rstrip("\\") + "\\"

    # --- Scan card for matching files ---
    matched = []
    for dirpath, _, files in os.walk(card_path):
        for fname in files:
            ext = os.path.splitext(fname)[1].upper().lstrip(".")
            if ext in extensions:
                matched.append(Path(dirpath) / fname)

    if not matched:
        ext_list = ", ".join(f".{e}" for e in sorted(extensions))
        messagebox.showinfo(
            "Card Unloader",
            f"No matching files found on card.\n\nLooked for: {ext_list}",
            parent=root,
        )
        return

    # --- Copy to primary destination ---
    primary = Path(primary_dest)
    copied = []
    for f in matched:
        dest = unique_dest(primary, f.name)
        shutil.copy2(f, dest)
        copied.append(dest)

    # --- Card can be removed ---
    messagebox.showinfo(
        "Card Unloader",
        f"{len(copied)} files copied to:\n{primary_dest}\n\n"
        "You can safely remove the card.",
        parent=root,
    )

    # --- Copy to backup ---
    if backup_dest and os.path.isdir(backup_dest):
        if os.path.realpath(primary_dest) != os.path.realpath(backup_dest):
            backup = Path(backup_dest)
            for f in copied:
                dest = unique_dest(backup, f.name)
                shutil.copy2(f, dest)

    # --- Launch Lightroom? ---
    if lightroom and os.path.isfile(lightroom):
        if messagebox.askyesno("Card Unloader", "Launch Lightroom?", parent=root):
            subprocess.Popen([lightroom])

    # --- Done ---
    messagebox.showinfo(
        "Card Unloader", f"Done \u2014 {len(copied)} files processed.", parent=root
    )


def main():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        run_unload(root)
    except Exception as e:
        messagebox.showerror("Card Unloader", f"Something went wrong:\n\n{e}", parent=root)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
