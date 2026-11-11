# Card Unloader

One-click SD card photo unloader for **macOS**.

> This is the macOS port (see the `Card Unloader.app` build below). Cards mount under `/Volumes`, and the standalone build is a Finder-launchable `.app` bundle instead of a Windows `.exe`.

## Setup (one time)

1. Run **`config_ui.py`** — from a terminal: `python3 config_ui.py`
2. Set your **Primary destination** and **Backup destination** folders
3. Set the **Lightroom app** path (click **Find** to auto-detect it in `/Applications`, or **Browse** to the `Adobe Lightroom….app` folder yourself)
4. Adjust **file extensions** if needed (default: `CR2, CR3, NEF, RAF, ARW, DNG, JPG, JPEG`)
5. Click **Save**
6. (Optional, recommended) Click **Build Standalone App** and choose a folder — you get a `Card Unloader.app` you can drag to your Desktop or dock, so you have a single thing to double-click

That's it. Close the settings window.

## Everyday use

1. Double-click **`Card Unloader.app`** (or run `python3 card_unloader.py` from a terminal if you haven't built the app)
2. When it asks, plug your camera card into the reader — the app waits for it to mount, then continues automatically
3. That's it — the app copies your photos to your folder, backs them up, tells you the card is safe to remove, and asks whether to launch Lightroom

## Files

| File | What it does |
|---|---|
| `card_unloader.py` | The program you run every day. Does the actual card detection, copying, and backup. |
| `config_ui.py` | The one-time setup window where you pick your folders and Lightroom app path. You only open this when something needs changing. |
| `config.json` | Where your saved settings live (created automatically when you first click Save). |

## Building the standalone app

Running the `.py` files needs Python installed. If you'd rather have a self-contained app that doesn't:

1. Open the settings window and click **Build Standalone App**.
2. It offers to `pip install pyinstaller` the first time (one-time).
3. It then asks **which folder** to put the app in (it creates `Card Unloader.app` inside; cancel and it lands next to `config_ui.py`). Nothing is ever written outside the project folder unless you pick a location.
4. The result is a `Card Unloader.app` — a Finder-launchable bundle with your current settings baked in. Drag it anywhere and double-click it; the app unpacks itself to a temp folder on launch, so there's nothing else to keep beside it.

> To change settings after building, edit them in the settings window, click **Save**, then **Build Standalone App** again and save over the old bundle — the new one embeds the updated settings.

## Notes

- No Python packages required — everything uses the standard library (PyInstaller is only needed for the optional standalone app)
- Cards are detected as they mount under `/Volumes` (FAT32/exFAT, like camera cards format); the Mac's own disks and network shares are ignored
- If the card is already plugged in when you launch, it's detected right away (real camera cards hold a `DCIM` folder, so FAT-formatted externals aren't mistaken for one)
- One window guides you through every stage — waiting for the card, scanning, copying (x-of-y progress bar), safe-to-remove, backup (its own bar), Lightroom — all by clicking buttons in that window
- Every run is logged to `card_unloader.log` beside the app (a Finder-launched app has no console); check that file if anything misbehaves
- A file whose destination rejects metadata still gets copied content-only; hard failures are listed in the Done screen instead of stopping the run
- Files are flattened into your destination folder (the card's `DCIM/…` structure is ignored)
- Hidden files and folders are skipped
- If a file already exists in the destination it gets a ` (1)`, ` (2)`, … suffix instead of overwriting
- If multiple card volumes are detected you'll be asked which one to use
