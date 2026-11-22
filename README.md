# L4D2 Survivor Swapper Tool | v2.0.1

> 🌐 **Language:** **English** | [Português (Brasil)](docs/README.pt-BR.md) | [Español](docs/README.es-ES.md)

An automated, headless toolchain and modern Fluent Desktop GUI for porting **Left 4 Dead 2** survivor `.vpk` mods between any of the 8 survivors (`Bill`, `Zoey`, `Louis`, `Francis`, `Nick`, `Rochelle`, `Coach`, and `Ellis`), complete with batch queues, Workshop downloads, and built-in GitHub updates.

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start & Walkthrough](#quick-start--walkthrough)
  - [1. First-Run Setup Wizard](#1-first-run-setup-wizard)
  - [2. Single Mod Conversion (`Swap`)](#2-single-mod-conversion-swap)
  - [3. Pre-Conversion Confirmation](#3-pre-conversion-confirmation)
  - [4. Batch Queue (`Batch`)](#4-batch-queue-batch)
  - [5. My Survivor Mods (`My Mods`)](#5-my-survivor-mods-my-mods)
  - [6. Steam Workshop Downloader (`Download`)](#6-steam-workshop-downloader-download)
  - [7. Conversion History (`History`)](#7-conversion-history-history)
  - [8. Environment Diagnostics (`Environment`)](#8-environment-diagnostics-environment)
  - [9. Built-in Updater (`Updates`)](#9-built-in-updater-updates)
  - [10. Settings & Preferences (`Settings`)](#10-settings--preferences-settings)
- [Output Naming & Metadata Placeholders](#output-naming--metadata-placeholders)
- [Headless CLI Batch Mode](#headless-cli-batch-mode)
- [Project Architecture](#project-architecture)
- [Sharing / Distributing a Clean Copy](#sharing--distributing-a-clean-copy)
- [Running Tests](#running-tests)
- [Contact, Credits & License](#contact-credits--license)

---

## Requirements

- **Windows 10 / 11**
- **Python 3.10+** (`3.13` recommended) — check **"Add Python to PATH"** during installation
- **Left 4 Dead 2** installed via Steam (`AppID 550`)
- **Left 4 Dead 2 Authoring Tools** installed via Steam Library → Tools (`AppID 563`, provides `studiomdl.exe` and `vpk.exe`)

Python dependencies ([`requirements.txt`](requirements.txt)): `PySide6>=6.9.0`, `PySide6-Fluent-Widgets>=1.11.0`, `vpk>=1.4.0`, `vdf>=3.4`, `psutil>=5.9.0`.

---

## Installation

### Option A — Easy Windows Setup (Recommended)

1. Download or extract the tool folder anywhere on your PC (e.g., `C:\L4D2-Survivor-Swapper-Tool\`).
2. Make sure **Left 4 Dead 2** and **Left 4 Dead 2 Authoring Tools** are installed in Steam.
3. Double-click [`_INSTALL_REQUIREMENTS.bat`](_INSTALL_REQUIREMENTS.bat) to install all Python packages automatically.
4. Double-click [`_RUN.bat`](_RUN.bat) to launch the application (runs silently via `pythonw` when available).

### Option B — Terminal / PowerShell Setup

```powershell
git clone https://github.com/SirCaveiraOFC/L4D2-Survivor-Swapper-Tool.git
cd L4D2-Survivor-Swapper-Tool
pip install -r requirements.txt
python app.py
```

*(If you want to rebuild [`MdlDecompilerCli.exe`](tools/mdl_decompiler_cli/MdlDecompilerCli.exe) from ZeqMacaw's Crowbar VB.NET source, see [`tools/mdl_decompiler_cli/build.ps1`](tools/mdl_decompiler_cli/build.ps1) and [`tools/mdl_decompiler_cli/NOTICE.txt`](tools/mdl_decompiler_cli/NOTICE.txt).)*

---

## Quick Start & Walkthrough

### 1. First-Run Setup Wizard

On first launch (or whenever L4D2 / Authoring Tools paths are missing), the **Setup Wizard** automatically detects Steam libraries, Left 4 Dead 2 (`AppID 550`), `studiomdl.exe` + `vpk.exe` (`AppID 563`), `MdlDecompilerCli.exe`, and lets you sync `%APPDATA%\ZeqMacaw\Crowbar 0.74\Crowbar Settings.xml` safely (creating a `.bak` backup first). You can also switch UI language right inside the wizard (`Auto`, `English`, `Português (Brasil)`, `Español`).

---

### 2. Single Mod Conversion (`Swap`)

1. Drag and drop any `.vpk`, compressed `.zip` / `.rar` / `.7z` archive (including multi-VPK packs with an interactive picker), or extracted mod folder onto Step 1 — or load directly from **L4D2 Addons / Workshop** or a **Workshop Link**.
2. Inspect the detected **Origin Survivor**, assets (`Body`, `Arms`, `VGUI`, `Physics`), and decoded `.vtf` VGUI portrait previews (Lobby, In-Game HUD, Incap HUD — click to zoom).
3. Select one or multiple target survivors grouped under **L4D1** and **L4D2** (or use quick buttons: `All Others`, `L4D1 Crew`, `L4D2 Crew`, `Clear`).
4. Customize output filename/title placeholders, metadata (`Author`, `Version`, `Description`), custom cover (`addonimage.jpg` / `.png`), and grouped **Conversion Options** (`Model Assets` and `Output & Metadata`), then click **Start Conversion**.

---

### 3. Pre-Conversion Confirmation

Before starting compilation, a summary modal lets you review the cover, source archive, `Origin -> Targets` route pills, exact generated `.vpk` filenames, active options, and navigate across queued jobs (`Previous` / `Next` or arrow keys `←` / `→`).

---

### 4. Batch Queue (`Batch`)

Queue dozens of mods at once from files, folders, installed L4D2 addons/workshop VPKs, or multiple Steam Workshop URLs/IDs:
- Set **Global Queue Defaults** (default targets, filename/title templates, and options) and apply them to all items with one click.
- Or uncheck **Use Global Defaults** per queued mod to customize its own targets, origin, cover image, metadata, and options independently.

---

### 5. My Survivor Mods (`My Mods`)

Inspect all active survivor replacements inside `left4dead2/addons/` and `addons/workshop/`:
- 8 clickable **Survivor Loadout Cards** highlighting active mods and potential slot conflicts.
- Filter by search query, folder (`addons` vs `workshop`), survivor/generation, and enabled status.
- Toggle mods on/off in `addonlist.txt`, zoom covers, delete `.vpk` files, send a mod straight into the **Swapper**, or launch L4D2.

---

### 6. Steam Workshop Downloader (`Download`)

Paste one or multiple Steam Workshop URLs or numeric IDs to inspect metadata and download `.vpk` files straight into `Workshop_Downloads/`:
- Shows community metrics (`Subscribers`, `Favorites`, `Visitors`, `File Size`), star rating, dates, clickable wrapped tags, and cover preview (supports animated GIFs and zoom modal).
- Detects non-survivor Workshop mods (e.g., `VScript`, `Campaigns`, `Weapons`, `Infected`, `HUD`, `Audio`) so you know when an item can be installed to `addons/` without survivor porting.
- Manage your local `Workshop_Downloads/` library at the bottom and send skins directly to **Single Swap**, **Batch Queue**, or `addons/`.
- Click **Read Full Description** (or click the summary box) to open a rich styled BBCode modal with clickable links, tables, quotes, spoilers, and lazily loaded Workshop images.

---

### 7. Conversion History (`History`)

Browse all completed, partial, cancelled, and failed swaps, inspect per-target generated `.vpk` paths, reopen any original source in **Swapper**, open the output directory, or reinstall results with automatic `addonlist.txt` conflict checks.

---

### 8. Environment Diagnostics (`Environment`)

Verify live status of Left 4 Dead 2, Authoring Tools (`studiomdl.exe`, `vpk.exe`), `MdlDecompilerCli.exe`, and `Crowbar Settings.xml`, trigger auto-detection, sync Crowbar XML settings, or reopen the Setup Wizard anytime.

---

### 9. Built-in Updater (`Updates`)

Keep the application up to date directly from GitHub without overwriting your settings or mods:
- Supports checking both **GitHub Releases** and the configured branch's `core/app_meta.py`.
- Previews the changelog / release notes and a per-file diff table (`+ New`, `~ Modified`, `- Removed`) before downloading or installing.
- Automatically protects user files and directories (`settings.json`, `conversion_history.json`, `Swapped_Survivors/`, `Survivor_Swap/`, `Workshop_Downloads/`), creates a safety backup before applying files, installs new dependencies if `requirements.txt` changed, and cleanly restarts when finished.

---

### 10. Settings & Preferences (`Settings`)

Configure paths (`L4D2 folder`, `studiomdl.exe`, `vpk.exe`, `Output VPK Folder`, `Workshop Downloads Folder`, `Swap Kit Folder`), preferences (`Auto-Install`, `Debug Mode`), live **Theme** (`Dark` by default, with `System` / `Light` selectable), **Language** (`Auto` / `en-US` / `pt-BR` / `es-ES`), and view **About** metadata.

---

## Output Naming & Metadata Placeholders

You can click tag chips or type any combination in **Output File Name** and **Addon Title**:

| Tag | Replaced With | Example |
|---|---|---|
| `{survivor}` | Target survivor display name (or lowercase ID in filenames) | `Nick` / `nick` |
| `{origin}` | Original mod survivor name | `Zoey` / `zoey` |
| `{orig_title}` | Cleaned original mod title (strips redundant origin survivor tags) | `Emma Frost` |
| `{title}` | Alias for `{orig_title}` | `Emma Frost` |
| `{generation}` | Target survivor crew (`L4D1` or `L4D2`) | `L4D2` |
| `{origin_generation}` | Original survivor crew (`L4D1` or `L4D2`) | `L4D1` |
| `{display_name}` | Always capitalized target display name | `Nick` |
| `{survivor_id}` | Internal Source model stem | `survivor_gambler` |

---

## Headless CLI Batch Mode

Check environment readiness:

```powershell
python app.py --check-env
```

Sync Crowbar `0.74` settings cleanly from CLI:

```powershell
python app.py --apply-crowbar-settings --check-env
```

Port a `.vpk` to specific target survivors:

```powershell
python app.py --cli --source "Survivor_Swap\emma-zoey.vpk" --dest bill louis francis nick rochelle coach ellis --output-name "emma-{survivor}"
```

Or port to all 7 other survivors automatically and install to `addons/`:

```powershell
python app.py --cli --source "Survivor_Swap\emma-zoey.vpk" --all-except-origin --output-name "emma-{survivor}" --install
```

Useful CLI flags: `--output-dir`, `--origin`, `--title`, `--author`, `--version`, `--description`, `--no-arms`, `--no-vgui`, `--no-weapons`, `--keep-temp`.

---

## Project Architecture

```text
.
├── app.py                              # Unified CLI & GUI entry point
├── _RUN.bat                            # Silent Windows launcher (uses pythonw when available)
├── _INSTALL_REQUIREMENTS.bat           # One-click pip installer for requirements.txt
├── requirements.txt                    # Python runtime dependencies
├── core/                               # Headless OOP engine & services
│   ├── addons_scanner.py               # Workshop/addons VPK scanner & addonlist.txt manager
│   ├── app_meta.py                     # Canonical app name, version, developer & GitHub meta
│   ├── archive_service.py              # Safe .zip/.rar/.7z archive inspection & extraction
│   ├── config_manager.py               # settings.json persistence and path resolution
│   ├── crowbar_settings.py             # Crowbar 0.74 XML validator/sync with .bak backup
│   ├── history_manager.py              # conversion_history.json persistence
│   ├── i18n.py                         # OS locale detection + en-US/pt-BR/es-ES translations
│   ├── mdl_toolchain.py                # MdlDecompilerCli, studiomdl.exe & cancellable runner
│   ├── models.py                       # Typed dataclasses, SurvivorId enum & SwapCancelledError
│   ├── qc_merger.py                    # AST-driven universal survivor & arms QC merger
│   ├── qc_parser.py                    # Quote/comment/brace-aware Source .qc parser
│   ├── smd_splitter.py                 # Auto-splits high-poly SMDs (>20k tris) for StudioMDL
│   ├── steam_bbcode.py                 # Steam Workshop BBCode to styled HTML converter
│   ├── steam_locator.py                # Registry & VDF Steam/L4D2/Authoring Tools locator
│   ├── survivors.py                    # SurvivorRegistry (model stems, arms, VGUI slots, kits)
│   ├── swap_engine.py                  # Transactional multi-target swap & placeholder engine
│   ├── updater.py                      # GitHub Release/Tree diff checker, ZIP stager & applier
│   ├── vpk_service.py                  # Safe VPK extraction (utf-8/latin-1), packing & addoninfo
│   ├── vtf_decoder.py                  # Native VTF texture decoder for VGUI portrait previews
│   └── workshop_downloader.py          # Steam Workshop API/HTML inspector & VPK downloader
├── ui/                                 # PySide6 + PySide6-Fluent-Widgets L4D2-themed GUI
│   ├── addon_ui_shared.py              # Shared mod tables, zoom, QThread teardown & grouped panels
│   ├── addons_browser_dialog.py        # Searchable addons/workshop picker & conflict resolver
│   ├── addons_page.py                  # My Mods loadout slots & addonlist.txt manager
│   ├── batch_page.py                   # Batch Queue conversion page with global/per-item overrides
│   ├── conversion_confirm_dialog.py    # Pre-conversion confirmation summary modal
│   ├── download_page.py                # Steam Workshop Download hub & local library
│   ├── environment_page.py             # Visual diagnostics for L4D2, Tools & Crowbar
│   ├── error_dialog.py                 # Scrollable conversion error modal with clipboard copy
│   ├── history_page.py                 # Conversion History page with 1-click reinstall & reload
│   ├── main_window.py                  # FluentWindow shell, sidebar navigation, theme & update badge
│   ├── settings_page.py                # Paths, theme/language defaults & About card
│   ├── setup_wizard.py                 # First-run automated environment & Crowbar Setup Wizard
│   ├── swap_page.py                    # Single Mod swap workflow, VGUI strip, progress & log panel
│   ├── theme.py                        # L4D2 Yellow/Red/Black/White palette, hover motion & repaint sync
│   ├── updates_page.py                 # Dedicated Updates page with changelog & changed files table
│   ├── widgets.py                      # Hero banner, drop zone, grouped survivor picker, zoom & badges
│   ├── workshop_description_dialog.py  # Scrollable rich-text BBCode description viewer
│   └── workshop_download_dialog.py     # Quick Workshop URL/ID download modal
├── docs/                               # Localized documentation (PT-BR / ES-ES)
├── tools/mdl_decompiler_cli/           # Headless Crowbar 0.74 VB.NET decompiler CLI + build script
├── HUNK'S_SURVIVOR_SWAP_KIT/           # Base donor QC/animation/rig templates per survivor
├── legacy/                             # Archived v1.x launchers and Crowbar.exe GUI binary
└── tests/                              # Unit & headless UI tests (pytest)
```

---

## Sharing / Distributing a Clean Copy

Before zipping the folder to share with another user, exclude personal/local data so the recipient gets a clean first-run experience:

- Delete `settings.json`, `conversion_history.json`, and `.update_manifest.json`.
- Empty or exclude `Survivor_Swap/`, `Swapped_Survivors/`, `Workshop_Downloads/`, `.pytest_cache/`, `__pycache__/`, and optionally `legacy/`.

---

## Running Tests

```powershell
pytest
```

---

## Contact, Credits & License

- **Contact** — Email: [srcaveiraoficial@gmail.com](mailto:srcaveiraoficial@gmail.com)
- **GitHub** — [SirCaveiraOFC/L4D2-Survivor-Swapper-Tool](https://github.com/SirCaveiraOFC/L4D2-Survivor-Swapper-Tool)
- **Sr.Caveira** — Creator, L4D2 Survivor Swapper architecture & automation
- **ZeqMacaw** — [Crowbar](https://github.com/ZeqMacaw/Crowbar) `.mdl` decompiler engine (notices in [`tools/mdl_decompiler_cli/NOTICE.txt`](tools/mdl_decompiler_cli/NOTICE.txt))
- **H.U.N.K** — `HUNK'S_SURVIVOR_SWAP_KIT` survivor `.qc` reference templates
- **Valve Corporation** — Source Engine SDK (`studiomdl.exe`, `vpk.exe`)

See [`LICENSE`](LICENSE) for license details.
