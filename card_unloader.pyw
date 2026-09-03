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


def _drive_type(path):
    return ctypes.windll.kernel32.GetDriveTypeW(path)


def _candidate_drives():
    """Return {drive_path: type_code} for drives a camera card could show up as.

    That's any removable drive, or any *fixed* drive other than the internal
    Windows drive — CFexpress/NVMe readers frequently register as fixed.
    """
    sys_drive = os.environ.get("SystemDrive", "C:").rstrip("\\").upper()
    out = {}
    for letter in ascii_uppercase:
        path = f"{letter}:\\"
        t = _drive_type(path)  # 0 when the letter isn't in use
        if t not in (2, 3):  # removable or fixed
            continue
        if t == 3 and letter + ":" == sys_drive:
            continue
        out[path] = t
    return out


def _has_entries(path):
    try:
        return any(os.scandir(path))
    except OSError:
        return False


def wait_for_card(root):
    """Show a 'plug in your card' dialog and wait until a card drive appears.

    Triggers when either a new card-type drive letter shows up, or a drive
    that was present but empty starts containing files (card readers like
    many CFexpress ones hold a permanent drive letter and only fill up when
    a card is inserted). Returns the drive root path, or None if cancelled.
    """
    baseline = _candidate_drives()
    had_content = {p: _has_entries(p) for p in baseline}
    result = [None]
    cancelled = [False]

    dialog = tk.Toplevel(root)
    dialog.title("Card Unloader")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    tk.Label(
        dialog, text="Waiting for your camera card…\n\nPlug it in now.",
        justify="center",
    ).pack(pady=(18, 10), padx=24)

    def do_cancel():
        cancelled[0] = True
        dialog.destroy()

    tk.Button(dialog, text="Cancel", command=do_cancel).pack(pady=(0, 14))

    def poll():
        if cancelled[0]:
            return
        now = _candidate_drives()
        found = []
        for p in sorted(now):
            if p not in baseline:
                found.append(p)  # new drive letter
            elif not had_content[p] and _has_entries(p):
                found.append(p)  # permanent reader that just got a card
        if found:
            dialog.destroy()
            if len(found) == 1:
                result[0] = found[0]
            else:
                result[0] = pick_drive(root, found)
            return
        dialog.after(500, poll)

    dialog.grab_set()
    dialog.after(500, poll)
    dialog.wait_window()
    return result[0]


def _is_hidden(path):
    """True for dotfiles or files/folders with the Windows Hidden attribute."""
    if os.path.basename(path).startswith("."):
        return True
    try:
        attrs = os.stat(path).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & 0x2)  # FILE_ATTRIBUTE_HIDDEN


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

    # --- Wait for camera card ---
    card_path = wait_for_card(root)
    if card_path is None:
        return
    card_path = card_path.rstrip("\\") + "\\"

    # --- Scan card for matching files (skip hidden files & folders) ---
    matched = []
    for dirpath, dirs, files in os.walk(card_path):
        dirs[:] = [d for d in dirs if not _is_hidden(os.path.join(dirpath, d))]
        for fname in files:
            if _is_hidden(os.path.join(dirpath, fname)):
                continue
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
