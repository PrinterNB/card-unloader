"""Card Unloader — one-click SD card photo unloader (Windows).

One visible window walks the user through every stage — waiting for the card,
scanning, copying to the primary folder, removing the card, backup copy,
photo editor — with a live status line, text progress bar, and per-phase
estimates (x of y, ≈m:ss left, MB/s). All prompts are buttons in this one
window (no blocking message dialogs, no hidden root windows): click
callbacks and after() chains keep Tk's mainloop in charge, so the bar
visibly advances instead of freezing. Every run is logged to
card_unloader.log beside the exe (or beside this .pyw), since a
double-clicked app has no console. Windows card detection is unchanged from
the classic version: GetDriveTypeW over every drive letter, SystemDrive
skipped.
"""
import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from string import ascii_uppercase
import tkinter as tk

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built exe; config.json is embedded and extracted here.
    BASE_DIR = Path(getattr(sys, "_MEIPASS"))
else:
    BASE_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = BASE_DIR
CONFIG_FILE = BASE_DIR / "config.json"


def _log_file():
    """Where the run log lives: beside the built exe, or beside this .pyw.

    A --onefile exe unpacks itself to a temp folder on each launch, so BASE_DIR
    isn't a stable place for the log — sys.argv[0] is the real exe, so its
    folder is where the log goes.
    """
    if getattr(sys, "frozen", False) and sys.argv:
        return Path(os.path.realpath(sys.argv[0])).parent / "card_unloader.log"
    return SCRIPT_DIR / "card_unloader.log"


LOG_FILE = _log_file()


# ---------- Windows drive detection (unchanged from the classic version) ----------

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


# ---------- config & filesystem helpers (no Tk involved) ----------

def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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


def _copy_file(src, dest):
    """Copy a file; never raise. Falls back to content-only when metadata
    (timestamps) is rejected — typical on network/SMB-backed destination
    folders. Returns False only if the data itself could not be written."""
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


def _editor_name(path):
    """Display name for the photo editor: exe basename without the extension."""
    if not path:
        return ""
    name = Path(path).name
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name


# ---------- the one-window UI ----------

class App:
    """Root window UI. Entirely event-driven: prompts show buttons and the
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

        The bar is text (█ filled, ░ remaining) inside the label, not a
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


def _rate(nbytes, secs):
    """Throughput of the current phase, e.g. "23.4 MB/s" or "512 KB/s"."""
    if secs <= 0:
        return ""
    kb = nbytes / secs / 1024
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB/s"
    return f"{kb:.0f} KB/s"


def copy_async(app, files, dest_dir, label, on_done):
    """Copy one file per after() callback so Tk's mainloop repaints between
    files — the progress bar visibly advances instead of freezing.
    Also shows a minutes:seconds estimate of what's left in this phase."""
    root = app.root
    dest = Path(dest_dir)
    total = max(len(files), 1)
    copied, failed = [], []
    nbytes = [0]
    t0 = time.monotonic()
    app.stage(f"{label} — 0 of {total} — estimating…", 0.0)

    def step(i):
        if i < len(files):
            f = files[i]
            try:
                nbytes[0] += Path(f).stat().st_size
            except OSError:
                pass
            d = unique_dest(dest, Path(f).name)
            if _copy_file(f, d):
                copied.append(d)
            else:
                failed.append(Path(f).name)
            done = i + 1
            line = f"{label} — {done} of {total}"
            eta = _eta(t0, done, total)
            if eta:
                line += f" — {eta}"
            rate = _rate(nbytes[0], time.monotonic() - t0)
            if rate:
                line += f" — {rate}"
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
                      "Logged — check card_unloader.log beside this app.")
            app.show_buttons({"Quit": quit})

    def finish(copied, failed, note=""):
        done_text = f"Done — {len(copied)} files processed."
        if failed:
            done_text += (
                f"\n\n{len(failed)} files could not be copied "
                "(destination permission or disk issue):\n"
                + "\n".join(f"• {name}" for name in failed[:8])
            )
        if note:
            done_text += f"\n\n{note}"
        app.stage(done_text)
        logging.info("session complete: copied=%d failed=%d", len(copied), len(failed))
        app.show_buttons({"Quit": quit})

    def after_backup(copied, failed, note=""):
        if editor and os.path.isfile(editor):
            app.stage(f"Copies done. Launch {editor_name}?\n\n{editor}")
            app.show_buttons({
                "Yes": lambda: safe(lambda: launch_then_finish(copied, failed, note)),
                "No": lambda: safe(lambda: finish(copied, failed, note)),
            })
            return
        finish(copied, failed, note)

    def launch_then_finish(copied, failed, note=""):
        app.stage(f"Launching {editor_name}…")
        subprocess.Popen([editor])
        finish(copied, failed, note)

    def run_backup(copied, failed):
        if backup_dest and os.path.isdir(backup_dest):
            if os.path.realpath(primary_dest) != os.path.realpath(backup_dest):
                # Backup always copies from the just-copied PRIMARY files, not
                # the card — the user was already told to remove it, so it may
                # be gone by now.
                logging.info("backup source: %d files in primary_dest (card not needed)", len(copied))
                copy_async(app, copied, backup_dest, "Copying to backup",
                           lambda c2, f2: after_backup(copied, failed + f2))
                return
            note = "Backup folder is the same as primary (no duplicates made)"
        elif backup_dest:
            note = f"Backup folder not found: {backup_dest} (skipped)"
        else:
            note = "No backup folder set (add one in Settings for mirrored copies)"
        after_backup(copied, failed, note)

    def on_primary_done(copied, failed):
        if not copied:
            app.stage(f"Could not copy any files to:\n{primary_dest}\n\n"
                      "Check the folder exists and is writable.")
            app.show_buttons({"Quit": quit})
            return
        app.stage(f"{len(copied)} files copied to:\n{primary_dest}\n\n"
                  "You can safely remove the card.")
        app.show_buttons({"Continue": lambda: safe(lambda: run_backup(copied, failed))})

    def on_card(drive):
        # Classic Windows handling: one trailing backslash on the drive root.
        card_root = drive.rstrip("\\") + "\\"

        def do_scan():
            app.stage(f"Card detected: {card_root}\n\nScanning your card…")
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
                app.show_buttons({"Quit": quit})
                return
            logging.info("matched %d files on %s", len(matched), card_root)
            copy_async(app, matched, primary_dest, "Copying to primary", on_primary_done)
        root.after(5, lambda: safe(do_scan))

    def handle_found(found):
        app._clear_buttons()  # drop the Cancel button
        if len(found) == 1:
            on_card(found[0])
            return
        app.stage("Multiple cards detected.\n\nClick the one you want to unload:")
        # Drive letters are unique, so each label (e.g. "D:") identifies one card.
        opts = {p.rstrip("\\"): (lambda p=p: safe(lambda: on_card(p))) for p in found}
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
    editor = cfg.get("editor_path", "").strip()
    editor_name = _editor_name(editor)
    logging.info("config: exts=%s primary=%r backup=%r editor=%r",
                 sorted(extensions), primary_dest, backup_dest, editor)
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
    baseline = _candidate_drives()
    had_content = {p: _has_entries(p) for p in baseline}
    logging.info("candidate drives at launch: %s", sorted(baseline))
    app.stage("Waiting for your camera card…\n\nPlug it in now.")
    app.show_buttons({"Cancel": lambda: (app.stage("Cancelled — nothing was copied."),
                                          app.show_buttons({"Quit": quit}))})

    def poll():
        now = _candidate_drives()
        found = []
        for p in sorted(now):
            if p not in baseline:
                found.append(p)  # new drive letter appeared
            elif not had_content[p] and _has_entries(p):
                found.append(p)  # permanent reader that just got a card
        if found:
            logging.info("card drives detected: %s", found)
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
        logging.info("app closed (window closed or Tcl exit)")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
