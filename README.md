# Card Unloader

One-click SD card photo unloader for Windows.

## Setup (one time)

1. Double-click **`config_ui.pyw`** (or the "Card Unloader Settings" desktop icon)
2. Set your **Primary destination** and **Backup destination** folders
3. Verify the **Lightroom path** is correct (click **Find** to auto-detect)
4. Adjust **file extensions** if needed (default: `CR2, CR3, NEF, RAF, ARW, DNG, JPG, JPEG`)
5. Click **Save**
6. Click **Create Desktop Shortcuts**

That's it. Close the settings window.

## Everyday use

1. Insert your camera card
2. Click **`Unload Card`** on your desktop
3. That's all — the app finds the card, copies your photos, backs them up, and asks whether to launch Lightroom

## Files

| File | What it does |
|---|---|
| `card_unloader.pyw` | Main flow — run via the **Unload Card** desktop icon |
| `config_ui.pyw` | Settings GUI — run via **Card Unloader Settings** desktop icon |
| `config.json` | Your saved settings (created automatically) |

## Optional: standalone EXE

By default the desktop icon runs `card_unloader.pyw` through Python (`pythonw`), so it needs Python installed. If you'd rather have a single self-contained `.exe`:

1. Open the settings window and click **Build Standalone EXE**.
2. It offers to `pip install pyinstaller` the first time (one-time), then builds `dist/Card Unloader.exe` with your current settings baked in.
3. It then repoints the **Unload Card** desktop shortcut at that exe, so the daily icon is a real standalone app.

> To change settings after building, edit them in the settings window, click **Save**, then **Build Standalone EXE** again — the new exe embeds the new settings.

## Notes

- No Python packages required — everything uses the standard library (PyInstaller is only needed for the optional standalone EXE)
- Files are flattened into your destination folder (the card's `DCIM/100MXXX/` structure is ignored)
- If a file already exists in the destination it gets a ` (1)`, ` (2)`, … suffix instead of overwriting
- If multiple removable drives are detected you'll be asked which one to use
