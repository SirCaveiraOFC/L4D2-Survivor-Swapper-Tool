# Changelog

All notable changes to **L4D2 Survivor Swapper Tool** are documented here.

## [2.1.0] - 2026-11-24

- **Portable Windows Edition (`.exe`)**: Added native `L4D2 Survivor Swapper Tool.exe` launcher and portable packaging script (`tools/build_portable.ps1`) with an embedded Python 3.13.5 runtime (no Python installation required).
- **Application Icon**: Added custom multi-resolution `ui/app_icon.ico`, applied across the `.exe` launcher, window title bar, and Windows taskbar (both portable `.exe` and `.py` launches).
- **Full Output Preview**: Updated `Swap` and `Batch` output previews to list every selected target survivor cleanly without `+N more` truncation.
- **Updater & Launchers**: Protected `runtime/` and `dist/` during in-app updates, added automatic `.exe` relaunch support for portable builds, and updated `_RUN.bat`, `_INSTALL_REQUIREMENTS.bat`, and README guides.
- **License**: Switched project license from MIT to **PolyForm Noncommercial 1.0.0** (`Sr.Caveira`), keeping the tool free to use and modify for noncommercial purposes with third-party notices preserved.

## [2.0.1] - 2026-11-22

- Refined Light/Dark theme consistency and changelog link colors in the Updates page and Workshop description viewer.

## [2.0.0] - 2026-11-22

- Complete desktop rewrite with Fluent UI (`PySide6`), automated headless Crowbar CLI (`MdlDecompilerCli.exe`), Batch Queue, L4D2 Addons Loadout viewer, Steam Workshop Downloader, Conversion History, Environment Setup Wizard, Multi-language UI (EN / PT-BR / ES), and Built-in GitHub Updater.

## [1.0.0] - 2024-10-29

- Initial CLI/batch Python release for converting Left 4 Dead 2 survivor mods using the H.U.N.K Survivor Swap Kit and Crowbar GUI.
