# 🎵 FLAC Damage Scanner & Fake FLAC Detector

**by Roby77**

A modern, bilingual (English/Italian) GUI tool to scan your music library for damaged FLAC files, fake FLACs (files with `.flac` extension that are actually another format), and FLAC files with leading ID3 tags that cause playback issues in strict players.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-1f6feb)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![Version](https://img.shields.io/badge/Version-8.2-green)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

- **🔍 Deep FLAC Validation** — Checks STREAMINFO block integrity, sample rate, channels, bit depth, and total samples.
- **🎭 Fake FLAC Detection** — Identifies files renamed to `.flac` that are actually MP3, OGG, WAV, AAC, APE, WavPack, M4A, or unknown formats.
- **🟡 Leading Tag Detection** — Finds FLAC files with ID3 tags prepended before the `fLaC` marker (causes "0 channels" errors in strict players).
- **🔧 One-Click Repair** — Strips leading ID3 tags safely (creates `.bak` backup), restoring playability.
- **🔧 Smart Rename** — Automatically renames fake FLACs to their correct extension (`.mp3`, `.ogg`, `.wav`, etc.).
- **⚡ Caching System** — Skips unchanged files on subsequent scans (based on mtime + size), dramatically speeding up re-scans.
- **🧪 Deep Verification** — Optional bit-perfect decode test using `flac -t` or `ffmpeg` (only on suspicious files).
- **📊 Per-Folder Report** — Beautiful, color-coded report grouped by folder with summary statistics.
- **🎯 Smart Filters** — Show only problems, only repairable files, or only fake FLACs.
- **🖱️ Context Menu** — Right-click any file to play it or open its folder. Double-click to play.
- **📋 Clipboard Export** — Copy lists of problematic files, fake FLACs, or repairable files.
- **💾 Save Report** — Export the full report to a text file.
- **🌍 Bilingual UI** — Switch between English and Italian on the fly with the `🌐` button.
- **🔄 Auto-Update Check** — Checks GitHub for newer releases at startup (and on demand).
- **🎨 Modern UI** — Built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) for a clean, rounded, dark-mode interface.
- **💻 Cross-Platform** — Works on Windows, macOS, and Linux.

---

## 🆕 What's New in v8.2

- **English is the default language** — the UI starts in English; click `🌐 EN → IT` to switch to Italian.
- **Automatic update check** — on startup, the app queries GitHub for the latest release (falls back to `version.txt` on the `main` branch).
- **Manual update check button** — `🔄 Check updates` in the options row.
- **Layout fix** — the language toggle no longer overlaps the "Start Scan" button (moved into the top row with proper `pack()` layout).
- **Window title** now shows `by Roby77`.

### Changelog history

| Version | Highlights |
|---------|------------|
| **8.2** | Bilingual UI (EN default), GitHub auto-update check, layout fix, `by Roby77` title |
| **8.1** | Italian/English translation system, language toggle button |
| **8.0** | Complete rewrite with CustomTkinter, modern dark UI |
| **7.0** | Tkinter version with per-folder report and cache |

---

## 📸 Screenshot

> *Add a screenshot of the application here.*

---

## 🚀 Installation

### Prerequisites

- **Python 3.8+**
- **CustomTkinter** (install via pip, see below)
- **(Optional but recommended)** `flac` and/or `ffmpeg` in your PATH for deep verification

### Install dependencies

```bash
pip install customtkinter
🎮 Usage
Select a folder containing your FLAC files using the Browse / Sfoglia button.

(Optional) Enable Deep verification to run flac -t / ffmpeg on suspicious files.

Click Start Scan / Avvia Scansione.

Review the color-coded report:

✅ Green — Valid FLAC file

🟡 Yellow — FLAC with leading tag (repairable)

🎭 Purple — Fake FLAC (wrong format)

❌ Red — Genuinely damaged FLAC

Use the repair tools:

🔧 Repair FLAC leading tag — Strips leading ID3 tags (creates .bak backups)

🔧 Rename fake FLACs — Renames fake FLACs to the correct extension

Tips
Double-click any file in the report to play it with your default player.

Right-click for a context menu (Play / Open folder / Copy path).

Use 🔄 Force rescan to ignore the cache and re-scan everything.

Use 🗑 Clear cache to clear the cache file (~/.flac_scanner_cache.json).

Click 🌐 EN → IT to switch language at any time (the report re-renders in the new language).

🧠 How It Works
Header Analysis (Fast Phase)
For every .flac file, the tool reads the first 42 bytes and validates:

Check	Description
Magic bytes	Must start with fLaC (or be flagged as having a leading tag)
First metadata block	Must be STREAMINFO (type 0)
STREAMINFO length	Must be exactly 34 bytes
Sample rate	Must be > 0
Channels	Must be 1–8
Bit depth	Must be ≥ 4
Total samples	Must be > 0 (warns on DURATA_ZERO)
If the file doesn't start with fLaC, the tool scans up to 10 MB ahead to detect a FLAC file with a prepended tag, and identifies the real format of fake FLACs.

Deep Verification (Optional Phase)
Only runs on files already flagged as suspicious (excludes known fake FLACs). Uses:

flac -t (preferred)

ffmpeg -v error -i <file> -f null - (fallback)

Caching
Results are stored in ~/.flac_scanner_cache.json keyed by folder. On re-scan, files are skipped if their mtime and size match the cached entry. The cache is automatically invalidated when you modify or rename files.

🔄 Auto-Update Check
On startup (after ~2 seconds), the app queries:

Primary: https://api.github.com/repos/Roby77ita/Find-damaged-fake-FLAC/releases/latest

Fallback: https://raw.githubusercontent.com/Roby77ita/Find-damaged-fake-FLAC/main/version.txt

If a newer version is found, a dialog offers to open the download page. The same check can be triggered manually with 🔄 Check updates.

To make the auto-update work, either:

Publish a GitHub Release with a tag like v8.3 (recommended), or

Keep a version.txt file in the main branch containing the latest version number (e.g. 8.2).

📁 Cache Location
OS	Path
Windows	C:\Users\<You>\.flac_scanner_cache.json
macOS	/Users/<You>/.flac_scanner_cache.json
Linux	/home/<You>/.flac_scanner_cache.json
⚠️ Safety Notes
Backups are created before any destructive operation:

strip_id3_prefix creates <file>.flac.bak

rinomina_sicura never overwrites existing files (adds _1, _2, etc.)

No files are deleted by this tool — only renamed or stripped.

Fake FLACs with unknown formats are not renamed (you'll be warned in the preview).

Deep verification can be slow on large libraries — use it selectively.

🛠️ Command-Line Alternatives
If flac is missing, the tool falls back to ffmpeg. If neither is installed, deep verification is skipped with a warning.

bash
# Verify a FLAC file
flac -t file.flac

# Or with ffmpeg
ffmpeg -v error -i file.flac -f null -
🗂️ Project Structure
text
.
├── Find damaged or fake FLAC 8.2.py   # Main application (CustomTkinter)
├── version.txt                         # Current version (for auto-update)
├── README.md                           # This file
└── LICENSE                             # MIT License
🤝 Contributing
Contributions, bug reports, and feature requests are welcome! Feel free to open an issue or submit a pull request.

Development
The codebase is a single Python file using only the standard library plus customtkinter. No build step required.

bash
git clone https://github.com/Roby77ita/Find-damaged-fake-FLAC.git
cd Find-damaged-fake-FLAC
pip install customtkinter
python "Find damaged or fake FLAC 8.2.py"
Adding a new language
Add a new key to the TRANSLATIONS dict (e.g. "es" for Spanish).

Copy all keys from the "en" block and translate the values.

Update _toggle_language() to cycle through available languages.

📄 License
This project is licensed under the MIT License — see the LICENSE file for details.

🙏 Acknowledgments
Built with CustomTkinter for a modern, dependency-light GUI.

Uses flac and ffmpeg for deep verification.

Inspired by the need to maintain a clean, playable music library.

⭐ Show Your Support
If this tool saved your music library, give it a ⭐ on GitHub! It helps others find it too.

📬 Contact
Have questions or suggestions? Open an issue on GitHub.

