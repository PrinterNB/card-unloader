# Card Unloader

> **macOS:** a macOS port lives on the [`macos-port` branch](https://github.com/PrinterNB/card-unloader/tree/macos-port) — same features, `.app` bundle build, `/Volumes` card detection. See its [README](https://github.com/PrinterNB/card-unloader/blob/macos-port/README.md).

One-click SD card photo unloader for Windows.

## Setup (one time)

1. Double-click **`config_ui.pyw`** to open the settings window
2. Set your **Primary destination** and **Backup destination** folders
3. Verify the **Lightroom path** is correct (click **Find** to auto-detect)
4. Adjust **file extensions** if needed (default: `CR2, CR3, NEF, RAF, ARW, DNG, JPG, JPEG`)
5. Click **Save**
6. (Optional, recommended) Click **Build Standalone EXE** and save `Card Unloader.exe` somewhere convenient — e.g. your desktop — so you have a single file to double-click.

That's it. Close the settings window.

## Everyday use

1. Double-click **`Card Unloader.exe`** (or `card_unloader.pyw` if you haven't built the exe)
2. When it asks, plug your camera card into the reader — the app waits for it, then continues automatically
3. That's it — the app copies your photos to your folder, backs them up, tells you the card is safe to remove, and asks whether to launch Lightroom

## Files

| File | What it does |
|---|---|
| `card_unloader.pyw` | The program you run every day. Does the actual card detection, copying, and backup. |
| `config_ui.pyw` | The one-time setup window where you pick your folders and Lightroom path. You only open this when something needs changing. |
| `config.json` | Where your saved settings live (created automatically when you first click Save). |

## Building the standalone EXE

Running the `.pyw` files needs Python installed. If you'd rather have a self-contained app that doesn't:

1. Open the settings window and click **Build Standalone EXE**.
2. It offers to `pip install pyinstaller` the first time (one-time).
3. It then asks **where to save** the app (a Save-as dialog; cancel it and the exe lands next to `config_ui.pyw`). Nothing is ever written outside the project folder unless you pick a location.
4. The result is a single `Card Unloader.exe` — no supporting folder, your current settings baked in. Copy it anywhere and double-click it; it unpacks itself to a temp folder on launch, so there's nothing else to keep beside it.

> To change settings after building, edit them in the settings window, click **Save**, then **Build Standalone EXE** again and save over the old exe — the new one embeds the updated settings.

## Notes

- No Python packages required — everything uses the standard library (PyInstaller is only needed for the optional standalone EXE)
- Files are flattened into your destination folder (the card's `DCIM/100MXXX/` structure is ignored)
- Hidden files and folders are skipped
- If a file already exists in the destination it gets a ` (1)`, ` (2)`, … suffix instead of overwriting
- If multiple card drives are detected you'll be asked which one to use
