"""Card Unloader — one-click SD card photo unloader (macOS)."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built app; config.json is embedded and extracted here.
    BASE_DIR = Path(getattr(sys, "_MEIPASS"))
else:
    BASE_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = BASE_DIR
CONFIG_FILE = BASE_DIR / "config.json"

VOLUMES_ROOT = "/Volumes"
# Camera cards are FAT32/exFAT formatted (DCF spec), and some readers report
# Mac-format or NTFS. The Mac's own disks are apfs/hfs, network shares smbfs/
# afp/nfs — anything else mounted under /Volumes is a card candidate.
CARD_FSTYPES = {"msdos", "msdosx", "exfat", "vfat", "fat", "fat32", "ntfs", "ntfs-3g", "hfs", "hfsplus"}


def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _mounted_volumes():
    """Return {mount_point: fstype} for everything mounted, via /sbin/mount.

    Each line looks like:  msdos on /Volumes/UNTITLED (msdos, local, nodev, …)
    Device and mount-point names can contain spaces (e.g. SMB shares), so the
    fields are matched lazily up to " on " and the "(flags)" tail.
    Returns None if /sbin/mount couldn't be read.
    """
    try:
        r = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^(.+?) on (.+?) \(([^()]+)\)\s*$", line)
        if m:
            out[m.group(2)] = m.group(3).split(",")[0]
    return out


def _candidate_volumes():
    """Return {volume_path: fstype} for drives a camera card could show up as.

    That's a card-formatted filesystem mounted under /Volumes. The internal
    Macintosh HD disks are apfs, network shares are smbfs/afp/nfs, and plain
    folders that happen to live in /Volumes (not mounts) are skipped.
    """
    mounts = _mounted_volumes()
    if mounts is None:
        # Fallback: any real mount point under /Volumes.
        out = {}
        try:
            for e in os.scandir(VOLUMES_ROOT):
                if e.is_dir() and os.path.ismount(e.path):
                    out[e.path] = None
        except OSError:
            pass
        return out
    out = {}
    for path, fst in mounts.items():
        if not path.startswith(VOLUMES_ROOT + "/"):
            continue
        if fst not in CARD_FSTYPES:
            continue
        if not os.path.isdir(path):
            continue
        out[path] = fst
    return out


def _has_entries(path):
    try:
        return any(os.scandir(path))
    except OSError:
        return False


def _has_dcim(path):
    """True if path (or one folder inside it) contains a DCIM folder.

    Camera cards follow the DCF spec and hold their photos in DCIM/, so this
    tells a real card apart from a FAT-formatted external drive that happens
    to be mounted at startup.
    """
    try:
        entries = [e for e in os.scandir(path) if e.is_dir()]
    except OSError:
        return False
    if any(e.name.lower() == "dcim" for e in entries):
        return True
    for e in entries:
        try:
            if any(e2.name.lower() == "dcim" for e2 in os.scandir(e.path) if e2.is_dir()):
                return True
        except OSError:
            pass
    return False


def wait_for_card(root):
    """Show a 'plug in your card' dialog and wait until a card volume appears.

    A card already mounted when the app started is detected immediately if it
    looks like a camera card (DCIM folder) — otherwise triggers when either a
    new card volume shows up under /Volumes, or a volume that was present but
    empty starts containing files (some readers keep a permanent mount point
    and only fill up when a card is inserted). Returns the volume root path,
    or None if cancelled.
    """
    baseline = _candidate_volumes()
    had_content = {p: _has_entries(p) for p in baseline}
    result = [None]
    cancelled = [False]

    already = [p for p in sorted(baseline) if had_content[p] and _has_dcim(p)]
    if already:
        return already[0] if len(already) == 1 else pick_drive(root, already)

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
        now = _candidate_volumes()
        found = []
        for p in sorted(now):
            if p not in baseline:
                found.append(p)  # new card volume
            elif not had_content[p] and _has_entries(p):
                found.append(p)  # permanent mount point that just got a card
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
    """True for dotfiles or MacOS X resource forks / AppleDouble files."""
    if os.path.basename(path).startswith("."):
        return True
    if os.path.basename(path).startswith("._"):
        return True  # AppleDouble sidecar (e.g. ._IMG_1234.CR3)
    return False


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
        lb.insert(tk.END, Path(d).name or d)
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


def _app_wrapper(path):
    """Return the .app bundle at or above path, or None.

    Users can browse straight into Contents/MacOS — Adobe apps must not be
    exec'd from there (nested helper bundles live beside the main exe), so
    any path inside a bundle is normalized up to the bundle itself and
    launched via Finder.
    """
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            bundle = Path(*parts[: i + 1])
            if bundle.is_dir():
                return bundle
    return None


def _is_launchable(path):
    """True for a Lightroom .app bundle, a path inside one, or an executable."""
    if _app_wrapper(path):
        return True
    p = Path(path)
    return p.is_file() and os.access(p, os.X_OK)


def _launch(path):
    """Launch Lightroom: Finder opens .app bundles, plain binaries run directly."""
    bundle = _app_wrapper(path)
    if bundle:
        subprocess.run(["open", str(bundle)])
    else:
        subprocess.Popen([str(path)])


def _copy_file(src, dest):
    """Copy with metadata; fall back to content-only on filesystems that
    reject them (SMB shares, some external drives). False = both failed."""
    try:
        shutil.copy2(src, dest)
        return True
    except OSError:
        try:
            shutil.copyfile(src, dest)
            return True
        except OSError:
            return False


class StatusWindow:
    """Floating panel showing the current stage and a progress bar."""

    BAR_W = 220

    def __init__(self, root):
        w = tk.Toplevel(root)
        w.title("Card Unloader")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        self.label = tk.Label(w, justify="left")
        self.label.pack(padx=14, pady=(12, 6))
        self.canvas = tk.Canvas(w, height=18, width=self.BAR_W + 6, border=0)
        self.canvas.pack(padx=14, pady=(2, 12))
        self.w = w

    def set(self, text, frac=None):
        """Show stage text; draw the bar when frac (0..1) is given."""
        self.label.configure(text=text)
        c = self.canvas
        c.delete("all")
        if frac is not None:
            frac = min(max(frac, 0.0), 1.0)
            x0, y0 = 4, 3
            c.create_rectangle(x0, y0, x0 + self.BAR_W, y0 + 12, outline="#808080")
            c.create_rectangle(x0, y0, x0 + int(self.BAR_W * frac), y0 + 12, fill="#4a90d9")
        self.w.update_idletasks()

    def close(self):
        self.w.destroy()


def run_unload(root):
    config = load_config()
    if config is None:
        messagebox.showerror(
            "Card Unloader",
            "Configuration not found.\n\n"
            "Open “Card Unloader Settings” to set up your folders first.",
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
            "Open “Card Unloader Settings” to configure.",
            parent=root,
        )
        return

    if not os.path.isdir(primary_dest):
        messagebox.showerror(
            "Card Unloader",
            f"Primary destination not found:\n{primary_dest}\n\n"
            "Open “Card Unloader Settings” to fix this.",
            parent=root,
        )
        return

    # --- Wait for camera card ---
    card_path = wait_for_card(root)
    if card_path is None:
        return
    card_root = Path(card_path)

    # --- Scan, copy, backup with a live status panel ---
    status = StatusWindow(root)
    try:
        status.set("Scanning your card…")
        matched = []
        for dirpath, dirs, files in os.walk(card_root):
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
        total = len(matched)
        copied, failed = [], []
        for i, f in enumerate(matched, 1):
            dest = unique_dest(primary, f.name)
            if _copy_file(f, dest):
                copied.append(dest)
            else:
                failed.append(f"{f.name} → primary")
            status.set(f"Copying to primary — {i} of {total}", i / total)

        if not copied:
            messagebox.showerror(
                "Card Unloader",
                f"Could not copy any files to:\n{primary_dest}\n\n"
                "Check the folder exists and is writable.",
                parent=root,
            )
            return

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
                n = len(copied)
                status.set(f"Copying to backup — 0 of {n}")
                for j, f in enumerate(copied, 1):
                    dest = unique_dest(backup, f.name)
                    if not _copy_file(f, dest):
                        failed.append(f"{f.name} → backup")
                    status.set(f"Copying to backup — {j} of {n}", j / n)

        # --- Launch Lightroom? ---
        if lightroom and _is_launchable(lightroom):
            if messagebox.askyesno("Card Unloader", "Launch Lightroom?", parent=root):
                status.set("Launching Lightroom…")
                _launch(lightroom)

        # --- Done ---
        done_text = f"Done — {len(copied)} files processed."
        if failed:
            done_text += (
                f"\n\n{len(failed)} could not be copied (destination permission or disk issue):\n"
                + "\n".join(f"• {t}" for t in failed[:8])
            )
        messagebox.showinfo("Card Unloader", done_text, parent=root)
    finally:
        status.close()


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
