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
import time
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


def _log_file():
    """Where the run log lives.

    For the Finder-built app BASE_DIR is a temp folder recreated on each
    launch, so write beside the .app bundle instead — the app can live
    anywhere and its log can still be found next to it.
    """
    if getattr(sys, "frozen", False) and sys.argv:
        exe = Path(os.path.realpath(sys.argv[0]))
        bundle = exe.parent.parent  # .../Card Unloader.app/Contents/MacOS/exe
        if bundle.suffix == ".app" and bundle.is_dir():
            return bundle.parent / "card_unloader.log"
    return SCRIPT_DIR / "card_unloader.log"


LOG_FILE = _log_file()

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
    """Root window UI. Entirely event-driven: dialogs show buttons and the
    flow continues from click callbacks, so Tk's mainloop (and its repaints)
    stay in charge at all times — heavy work must never run between clicks."""
    BAR_CELLS = 34

    def __init__(self, root):
        self.root = root
        root.title("Card Unloader")
        root.attributes("-topmost", True)
        self.text = tk.Label(root, justify="left")
        self.text.pack(padx=18, pady=(18, 12))
        self._buttons = []

    def stage(self, text, frac=None):
        """Set status line; when frac (0..1) is given, append a text bar.

        The bar is text (▓ filled, ░ remaining) inside the label, not a
        Canvas — it renders identically at any DPI/theme and can't be
        clipped by window sizing.
        """
        if frac is not None:
            done = min(self.BAR_CELLS, int(round(self.BAR_CELLS * max(0.0, frac))))
            bar = "█" * done + "░" * (self.BAR_CELLS - done)
            text = text + "\n\n" + bar
        self.text.configure(text=text)
        self.root.update_idletasks()
        logging.info("stage: %s", text.replace("\n", " | "))

    def show_buttons(self, options):
        """Show buttons for {label: callback}; a click runs that callback
        inside Tk's event loop (safe to open more dialogs or schedule more
        after() work from it). Shown buttons are removed on click."""
        for label, fn in options.items():
            def clickify(f=fn):
                self._clear_buttons()
                f()
            b = tk.Button(self.root, text=label, command=clickify)
            b.pack(pady=(0, 8))
            self._buttons.append(b)

    def _clear_buttons(self):
        for b in self._buttons:
            b.destroy()
        self._buttons = []


# ---------- the flow ----------

def _eta(t0, done, total):
    """Remaining-time estimate "m:ss" from the pace so far, or '' if exact end."""
    if done >= total:
        return ""
    avg = (time.monotonic() - t0) / max(done, 1)
    eta = avg * (total - done)
    return f"≈{int(eta // 60)}:{int(eta % 60):02d} left"


def copy_async(app, files, dest_dir, label, on_done):
    """Copy one file per after() callback so Tk's mainloop repaints between
    files — the progress bar visibly advances instead of beachballing.
    Also shows a minutes:seconds estimate of what's left in this phase."""
    root = app.root
    dest = Path(dest_dir)
    total = max(len(files), 1)
    copied, failed = [], []
    t0 = time.monotonic()
    app.stage(f"{label} — 0 of {total} — estimating…", 0.0)

    def step(i):
        if i < len(files):
            f = files[i]
            d = unique_dest(dest, Path(f).name)
            if _copy_file(f, d):
                copied.append(d)
            else:
                failed.append(Path(f).name)
            done = i + 1
            eta = _eta(t0, done, total)
            line = f"{label} — {done} of {total}"
            if eta:
                line += f" — {eta}"
            app.stage(line, done / total)
            root.after(25, lambda: step(i + 1))
        else:
            on_done(copied, failed)

    root.after(25, lambda: step(0))


def run_unload(app, quit):
    """Start the flow; everything past this point is callback/after driven
    so Tk's mainloop stays alive and repaints during heavy work."""
    root = app.root

    def safe(fn):
        """Run fn with a top-level trap: a crash becomes a visible screen + log."""
        try:
            fn()
        except Exception as e:
            logging.exception("flow crashed")
            app.stage(f"Something went wrong:\n\n{e}\n\n"
                      "(Logged — check card_unloader.log beside the app.)")
            app.show_buttons({"Quit": quit})

    def finish(copied, failed):
        done_text = f"Done — {len(copied)} files processed."
        if failed:
            done_text += (
                f"\n\n{len(failed)} files could not be copied "
                "(destination permission or disk issue):\n"
                + "\n".join(f"• {name}" for name in failed[:8])
            )
        app.stage(done_text)
        logging.info("session complete: copied=%d failed=%d", len(copied), len(failed))
        app.show_buttons({"Quit": quit})

    def after_backup(copied, failed):
        if lightroom and _is_launchable(lightroom):
            app.stage(f"Copies done. Launch Lightroom?\n\n{lightroom}")
            app.show_buttons({
                "Yes": lambda: safe(lambda: launch_then_finish(copied, failed)),
                "No": lambda: safe(lambda: finish(copied, failed)),
            })
            return
        finish(copied, failed)

    def launch_then_finish(copied, failed):
        app.stage("Launching Lightroom…")
        _launch(lightroom)
        finish(copied, failed)

    def run_backup(copied, failed):
        if backup_dest and os.path.isdir(backup_dest):
            if os.path.realpath(primary_dest) != os.path.realpath(backup_dest):
                logging.info("backup source: %d files in primary_dest (card not needed)", len(copied))
                copy_async(app, copied, backup_dest, "Copying to backup",
                           lambda c2, f2: after_backup(copied, failed + f2))
                return
            logging.info("backup same as primary; skipped")
        after_backup(copied, failed)

    def on_primary_done(copied, failed):
        if not copied:
            app.stage(f"Could not copy any files to:\n{primary_dest}\n\n"
                      "Check the folder exists and is writable.")
            app.show_buttons({"Quit": quit})
            return
        app.stage(f"{len(copied)} files copied to:\n{primary_dest}\n\n"
                  "You can safely remove the card.")
        app.show_buttons({"Continue": lambda: safe(lambda: run_backup(copied, failed))})

    def on_card(card_path):
        def do_scan():
            app.stage(f"Card detected: {Path(card_path).name}\n\nScanning your card…")
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
                app.stage(f"No matching files found on card.\n\nLooked for: {ext_list}")
                app.show_buttons({"Quit": quit})
                return
            logging.info("matched %d files on %s", len(matched), Path(card_path))
            copy_async(app, matched, primary_dest, "Copying to primary", on_primary_done)
        root.after(5, lambda: safe(do_scan))

    def handle_found(found):
        app._clear_buttons()  # drop the Cancel button
        if len(found) == 1:
            on_card(found[0])
            return
        app.stage("Multiple cards detected.\n\nClick the one you want to unload:")
        opts = {Path(v).name: (lambda p=v: safe(lambda: on_card(p))) for v in found}
        if len(opts) < len(found):  # name collision: show full paths
            opts = {v: (lambda p=v: safe(lambda: on_card(p))) for v in found}
        app.show_buttons(opts)

    # --- config & validation (fast, safe to run synchronously) ---
    cfg = load_config()
    if cfg is None:
        app.stage("Configuration not found.\n\n"
                  "Open “Card Unloader Settings” to set up your folders first.")
        app.show_buttons({"Quit": quit})
        return
    extensions = {e.upper().lstrip(".") for e in cfg.get("extensions", [])}
    primary_dest = cfg.get("primary_destination", "").strip()
    backup_dest = cfg.get("backup_destination", "").strip()
    lightroom = cfg.get("lightroom_path", "").strip()
    logging.info("config: exts=%s primary=%r backup=%r lr=%r",
                 sorted(extensions), primary_dest, backup_dest, lightroom)
    if not primary_dest:
        app.stage("Primary destination is not set.\n\n"
                  "Open “Card Unloader Settings” to configure.")
        app.show_buttons({"Quit": quit})
        return
    if not os.path.isdir(primary_dest):
        app.stage(f"Primary destination not found:\n{primary_dest}\n\n"
                  "Open “Card Unloader Settings” to fix this.")
        app.show_buttons({"Quit": quit})
        return

    # --- Wait for camera card (polling runs as after() callbacks) ---
    baseline = _candidate_volumes()
    had = {p: _has_entries(p) for p in baseline}
    logging.info("candidate volumes at launch: %s", sorted(baseline))
    already = [p for p in sorted(baseline) if had[p] and _has_dcim(p)]
    if already:
        logging.info("card already mounted at launch: %s", already)
        handle_found(already)
        return
    app.stage("Waiting for your camera card…\n\nPlug it in now.")
    app.show_buttons({"Cancel": lambda: (app.stage("Cancelled — nothing was copied."),
                                              app.show_buttons({"Quit": quit}))})

    def poll():
        now = _candidate_volumes()
        found = []
        for p in sorted(now):
            if p not in baseline:
                found.append(p)  # new card volume mounted
            elif not had[p] and _has_entries(p):
                found.append(p)  # permanent mount point just got a card
        if found:
            logging.info("card volumes detected: %s", found)
            handle_found(found)
            return
        root.after(500, poll)

    root.after(500, poll)


def main():
    try:
        logging.basicConfig(
            filename=str(LOG_FILE),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s: %(message)s",
        )
    except OSError:
        pass  # an unwritable log location must not break the run
    root = tk.Tk()
    app = App(root)

    def quit():
        try:
            root.quit()
        except Exception:
            pass

    def kickoff():
        try:
            run_unload(app, quit)
        except Exception as e:
            logging.exception("startup crashed")
            app.stage(f"Something went wrong:\n\n{e}")
            app.show_buttons({"Quit": quit})

    root.after(5, kickoff)
    try:
        root.mainloop()
    except Exception:
        logging.info("app quit (Cmd+Q or Tcl exit)")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
