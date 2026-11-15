# 🎵 FLAC Damage Scanner & Fake FLAC Detector

A powerful, user-friendly GUI tool to scan your music library for damaged FLAC files, fake FLACs (files with `.flac` extension that are actually another format), and FLAC files with leading ID3 tags that cause playback issues in strict players.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
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
- **🌍 Cross-Platform** — Works on Windows, macOS, and Linux.

---

## 📸 Screenshot

> *Add a screenshot of the application here.*

---

## 🚀 Installation

### Prerequisites

- **Python 3.8+** with `tkinter` (usually included with Python)
- **(Optional but recommended)** `flac` and/or `ffmpeg` in your PATH for deep verification

### Install dependencies

```bash
# Ubuntu / Debian
sudo apt install python3-tk flac ffmpeg

# macOS (Homebrew)
brew install python-tk flac ffmpeg

# Windows
# Tkinter is bundled with the official Python installer.
# Download flac and ffmpeg from their official sites and add them to PATH.
