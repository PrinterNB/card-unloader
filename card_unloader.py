"""Card Unloader — one-click SD card photo unloader (macOS).

One visible window walks the user through every stage — waiting for the card,
scanning, copying to the primary folder, removing the card, backup copy,
Lightroom — with a live status line and progress bar. All prompts are buttons
in this one window (no blocking message dialogs, no hidden root windows).
Every run is logged to card_unloader.log next to the app, since a Finder-
launched app has no stdout.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import tkinter as tk

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built app; config.json is embedded and extracted here.
    BASE_DIR = Path(getattr(sys, "_MEIPASS"))
else:
    BASE_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = BASE_DIR
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE = SCRIPT_DIR / "card_unloader.log"

VOLUMES_ROOT = "/Volumes"
# Camera cards are FAT32/exFAT (DCF spec). The Mac's own disks are apfs/hfs,
# network shares are smbfs/afp/nfs — anything card-formatted under /Volumes
# is a candidate.
CARD_FSTYPES = {"msdos", "msdosx", "exfat", "vfat", "fat", "fat32", "ntfs", "ntfs-3g"}


# ---------- config & filesystem helpers (no Tk involved) ----------

def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _mounted_volumes():
    """Return {mount_point: fstype} for everything mounted, via /sbin/mount.

    Lines look like:  msdos on /Volumes/UNTITLED (msdos, local, nodev, …)
    Device and mount-point names can contain spaces (SMB shares), so the
    fields are matched lazily up to " on " and the "(flags)" tail.
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
    """Return {volume_path: fstype} for drives a camera card could show up as."""
    mounts = _mounted_volumes()
    if mounts is None:  # /sbin/mount unreadable: accept any mount under /Volumes
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
    """True if path (or one folder inside it) holds a DCIM folder.

    Camera cards follow the DCF spec (photos live in DCIM/), which tells a
    real card apart from a FAT-formatted external drive at a glance.
    """
    try:
        dirs = [e for e in os.scandir(path) if e.is_dir()]
    except OSError:
        return False
    if any(e.name.lower() == "dcim" for e in dirs):
        return True
    for e in dirs:
        try:
            if any(e2.name.lower() == "dcim" for e2 in os.scandir(e.path) if e2.is_dir()):
                return True
        except OSError:
            pass
    return False


def _is_hidden(path):
    """True for dotfiles, AppleDouble sidecars, and card housekeeping dirs."""
    name = os.path.basename(path)
    return name.startswith(".") or name == "lost+found"


def unique_dest(dest_dir, filename):
    """Return a non-colliding path in dest_dir for the given filename."""
    p = Path(dest_dir) / filename
    stem, ext = p.stem, p.suffix
    counter = 1
    while p.exists():
        p = Path(dest_dir) / f"{stem} ({counter}){ext}"
        counter += 1
    return p


def _copy_file(src, dest):
    """Copy a file; never raise. Falls back to content-only when metadata
    (timestamps, xattrs) is rejected — typical on SMB/network-backed folders.
    Returns False only if the data itself could not be written."""
    try:
        shutil.copy2(src, dest)
        return True
    except OSError:
        try:
            shutil.copyfile(src, dest)
            return True
        except OSError as e:
            logging.warning("copy failed: %s -> %s: %s", src, dest, e)
            return False


def _app_wrapper(path):
    """The .app bundle at or above path, or None.

    Users can browse into a bundle (Contents/MacOS/…); Adobe apps must not be
    exec'd from there, so any path inside a bundle is normalized up to the
    bundle itself and launched via Finder.
    """
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            bundle = Path(*parts[: i + 1])
            if bundle.is_dir():
                return bundle
    return None


def _is_launchable(path):
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


# ---------- the one-window UI ----------

class App:
    """Root window that shows the current stage + progress bar, and waits
    on button clicks. Nothing in here blocks outside buttons()/update loop."""
    BAR_W = 240

    def __init__(self, root):
        self.root = root
        root.title("Card Unloader")
        root.attributes("-topmost", True)
        self.text = tk.Label(root, justify="left", wraplength=420)
        self.text.pack(padx=18, pady=(16, 8))
        self.canvas = tk.Canvas(root, height=18, width=self.BAR_W + 16, border=0)
        self.canvas.pack(padx=18, pady=(4, 14))
        self._frac = None

    def stage(self, text, frac=None):
        """Set status line; draw the bar when frac (0..1) given."""
        self._frac = frac
        self.text.configure(text=text)
        self._redraw_bar()
        self.root.update_idletasks()
        logging.info("stage: %s", text.replace("\n", " | "))

    def _redraw_bar(self):
        c = self.canvas
        c.delete("all")
        if self._frac is None:
            return
        frac = min(max(self._frac, 0.0), 1.0)
        x0, y0 = 8, 4
        c.create_rectangle(x0, y0, x0 + self.BAR_W, y0 + 12, outline="#808080")
        c.create_rectangle(x0, y0, x0 + int(self.BAR_W * frac), y0 + 12, fill="#4a90d9")

    def buttons(self, options):
        """Show buttons for {label: value}; block until one is clicked.

        Returns the value of the clicked button. Button widgets are removed
        afterwards so the window reads cleanly at the next stage.
        """
        self._choice = None
        made = []
        for label, value in options.items():
            def click(v=value):
                self._choice = v
            b = tk.Button(self.root, text=label, command=click)
            b.pack(pady=(0, 8))
            made.append(b)
        while self._choice is None:
            self.root.update()  # processes clicks; raises if the app is quit
        for b in made:
            b.destroy()
        return self._choice

    def wait_for_volume(self):
        """Detect the camera card. Returns its volume root, or None if cancelled.

        Already-mounted cards are detected immediately (only when they look
        like camera cards — DCIM); otherwise poll until a new card-formatted
        volume mounts, or a present-but-empty one fills up.
        """
        baseline = _candidate_volumes()
        had = {p: _has_entries(p) for p in baseline}
        already = [p for p in sorted(baseline) if had[p] and _has_dcim(p)]
        if already:
            logging.info("card already mounted at launch: %s", already)
            return already[0] if len(already) == 1 else self.pick_volume(already)

        self.stage("Waiting for your camera card…\n\nPlug it in now.")
        self._done = False
        cancel = tk.Button(self.root, text="Cancel",
                           command=lambda: setattr(self, "_done", True))
        cancel.pack(pady=(0, 8))
        self._card = None

        def poll():
            if self._done:
                return
            now = _candidate_volumes()
            found = []
            for p in sorted(now):
                if p not in baseline:
                    found.append(p)  # new card volume mounted
                elif not had[p] and _has_entries(p):
                    found.append(p)  # permanent mount point just got a card
            if found:
                logging.info("card volumes detected: %s", found)
                self._card = found[0] if len(found) == 1 else self.pick_volume(found)
                self._done = True
                return
            self.root.after(500, poll)

        poll()
        while not self._done:
            self.root.update()
        cancel.destroy()
        return self._card

    def pick_volume(self, volumes):
        """Multiple cards mounted: show one button per volume, return choice."""
        self.stage(
            "Multiple cards detected.\n\nClick the one you want to unload:"
        )
        options = {Path(v).name: v for v in volumes}
        if len(options) < len(volumes):  # name collision: fall back to full path
            options = {v: v for v in volumes}
        return self.buttons(options)

    def copy_many(self, files, dest_dir, stage_label):
        """Copy each file to dest_dir (unique names), live progress bar.

        Returns (copied_paths, [failed file names]).
        """
        dest_dir = Path(dest_dir)
        total = max(len(files), 1)
        copied, failed = [], []
        for i, f in enumerate(files, 1):
            dest = unique_dest(dest_dir, Path(f).name)
            if _copy_file(f, dest):
                copied.append(dest)
            else:
                failed.append(Path(f).name)
            self.stage(f"{stage_label} — {i} of {total}", i / total)
        return copied, failed


# ---------- the flow ----------

def run_unload(app):
    cfg = load_config()
    if cfg is None:
        app.stage(
            "Configuration not found.\n\n"
            "Open “Card Unloader Settings” to set up your folders first."
        )
        app.buttons({"Quit": None})
        return

    extensions = {e.upper().lstrip(".") for e in cfg.get("extensions", [])}
    primary_dest = cfg.get("primary_destination", "").strip()
    backup_dest = cfg.get("backup_destination", "").strip()
    lightroom = cfg.get("lightroom_path", "").strip()
    logging.info("config: exts=%s primary=%r backup=%r lr=%r",
                 sorted(extensions), primary_dest, backup_dest, lightroom)

    if not primary_dest:
        app.stage(
            "Primary destination is not set.\n\n"
            "Open “Card Unloader Settings” to configure."
        )
        app.buttons({"Quit": None})
        return

    if not os.path.isdir(primary_dest):
        app.stage(
            f"Primary destination not found:\n{primary_dest}\n\n"
            "Open “Card Unloader Settings” to fix this."
        )
        app.buttons({"Quit": None})
        return

    # --- Wait for camera card ---
    card_path = app.wait_for_volume()
    if card_path is None:
        app.stage("Cancelled — nothing was copied.")
        return
    card_root = Path(card_path)
    app.stage(f"Card detected: {Path(card_path).name}\n\nScanning your card…")

    # --- Scan card for matching files (skip hidden files & folders) ---
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
        app.stage(f"No matching files found on card.\n\nLooked for: {ext_list}")
        app.buttons({"Quit": None})
        return
    logging.info("matched %d files on %s", len(matched), card_root)

    # --- Copy to primary destination ---
    copied, failed = app.copy_many(matched, primary_dest, "Copying to primary")
    if not copied:
        app.stage(
            f"Could not copy any files to:\n{primary_dest}\n\n"
            "Check the folder exists and is writable."
        )
        app.buttons({"Quit": None})
        return

    # --- Card can be removed ---
    app.stage(
        f"{len(copied)} files copied to:\n{primary_dest}\n\n"
        "You can safely remove the card."
    )
    app.buttons({"Continue": None})

    # --- Copy to backup ---
    if backup_dest and os.path.isdir(backup_dest):
        if os.path.realpath(primary_dest) != os.path.realpath(backup_dest):
            _, bfailed = app.copy_many(copied, backup_dest, "Copying to backup")
            failed.extend(bfailed)
        else:
            logging.info("backup same as primary; skipped")

    # --- Launch Lightroom? ---
    if lightroom and _is_launchable(lightroom):
        app.stage(f"Copies done. Launch Lightroom?\n\n{lightroom}")
        if app.buttons({"Yes": True, "No": False}):
            app.stage("Launching Lightroom…")
            _launch(lightroom)

    # --- Done ---
    done_text = f"Done — {len(copied)} files processed."
    if failed:
        done_text += (
            f"\n\n{len(failed)} files could not be copied "
            "(destination permission or disk issue):\n"
            + "\n".join(f"• {name}" for name in failed[:8])
        )
    app.stage(done_text)
    logging.info("session complete: copied=%d failed=%d", len(copied), len(failed))
    app.buttons({"Quit": None})


def main():
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    root = tk.Tk()
    app = App(root)
    try:
        run_unload(app)
    except Exception as e:  # last-resort: log + show, never die silently
        logging.exception("session crashed")
        app.stage(f"Something went wrong:\n\n{e}\n\n(The error was logged.)")
        try:
            app.buttons({"Quit": None})
        except Exception:
            pass
    finally:
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
