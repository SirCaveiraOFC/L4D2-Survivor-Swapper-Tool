from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from core.app_meta import APP_META
from core.config_manager import ConfigManager
from core.crowbar_settings import CrowbarSettingsManager
from core.models import ModMetadata, SurvivorId, SwapJobRequest, SwapProgress
from core.steam_locator import SteamLocator
from core.survivors import SurvivorRegistry
from core.swap_engine import SwapEngine


PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="l4d2-survivor-swapper",
        description=f"{APP_META.window_title} — GUI & Headless Batch CLI",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run headless swap pipeline in CLI mode instead of launching the GUI.",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Inspect Steam, L4D2, Authoring Tools, MdlDecompilerCli, and Crowbar settings, then exit.",
    )
    parser.add_argument(
        "--apply-crowbar-settings",
        action="store_true",
        help="Sync recommended Crowbar 0.74 decompile & L4D2 settings before checking/swapping.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to the input survivor .vpk archive or extracted mod folder.",
    )
    parser.add_argument(
        "--origin",
        type=str,
        default=None,
        help="Original survivor replaced by the source mod (auto-detected if omitted).",
    )
    parser.add_argument(
        "--dest",
        nargs="+",
        type=str,
        default=None,
        help="One or more target survivors (e.g. bill louis francis nick rochelle coach ellis).",
    )
    parser.add_argument(
        "--all-except-origin",
        action="store_true",
        help="Target all 7 survivors other than the origin survivor.",
    )
    parser.add_argument(
        "--output-name",
        type=str,
        default="{title}_{survivor}",
        help="Output filename template supporting {survivor}, {display_name}, {survivor_id}, {title} (default: {title}_{survivor}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output folder for generated .vpk files (defaults to configured output_dir / Swapped_Survivors).",
    )
    parser.add_argument("--title", type=str, default=None, help="Override addoninfo.txt title.")
    parser.add_argument("--author", type=str, default=None, help="Override addoninfo.txt author.")
    parser.add_argument("--description", type=str, default=None, help="Override addoninfo.txt description.")
    parser.add_argument("--version", type=str, default=None, help="Override addoninfo.txt version.")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Copy generated .vpk files into Left 4 Dead 2 left4dead2/addons/.",
    )
    parser.add_argument("--no-arms", action="store_true", help="Skip converting first-person viewmodel arms.")
    parser.add_argument("--no-vgui", action="store_true", help="Skip converting VGUI lobby/HUD/incap portraits.")
    parser.add_argument("--no-weapons", action="store_true", help="Skip copying bundled weapon assets.")
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary decompile/compile staging folder when an error occurs.",
    )
    return parser


def _parse_survivor_list(values: list[str]) -> list[SurvivorId]:
    parsed: list[SurvivorId] = []
    seen: set[SurvivorId] = set()
    valid_names = ", ".join(s.value for s in SurvivorId)
    for raw in values:
        key = raw.strip().lower()
        try:
            sid = SurvivorId(key)
        except ValueError as exc:
            raise ValueError(f"Unknown survivor '{raw}'. Valid options: {valid_names}") from exc
        if sid not in seen:
            seen.add(sid)
            parsed.append(sid)
    return parsed


def _print_env_status(locator: SteamLocator, config_mgr: ConfigManager) -> int:
    config = config_mgr.load()
    status = locator.inspect_environment(config)
    print("=== L4D2 Survivor Swapper Environment Check ===")
    print(f"Steam Path         : {status.steam_path or 'Not Found'}")
    print(f"L4D2 Installed     : {status.l4d2_installed} ({status.l4d2_dir or 'Not Found'})")
    print(f"Authoring Tools    : {status.authoring_tools_installed}")
    print(f"  studiomdl.exe    : {status.studiomdl_path or 'Not Found'}")
    print(f"  vpk.exe          : {status.vpk_exe_path or 'Not Found'}")
    print(f"MdlDecompilerCli   : {status.decompiler_cli_path or 'Not Found'}")
    print(f"Crowbar Settings   : {status.crowbar_settings_path} (valid={status.crowbar_settings_valid})")
    if status.crowbar_issues:
        for issue in status.crowbar_issues:
            print(f"  - {issue}")
    print(f"Ready For Swap     : {status.is_ready_for_swap}")
    return 0 if status.is_ready_for_swap else 1


def _run_cli(args: argparse.Namespace) -> int:
    config_mgr = ConfigManager(project_root=PROJECT_ROOT)
    config = config_mgr.load()
    locator = SteamLocator(project_root=PROJECT_ROOT)
    env_status = locator.inspect_environment(config)

    if args.apply_crowbar_settings:
        mgr = CrowbarSettingsManager()
        if mgr.is_crowbar_running():
            print("[ERROR] Crowbar is currently running. Close Crowbar before updating its settings.", file=sys.stderr)
            return 1
        backup = mgr.apply(l4d2_dir=env_status.l4d2_dir, create_backup=True)
        print(f"[INFO] Applied recommended Crowbar 0.74 settings (backup: {backup})")
        env_status = locator.inspect_environment(config)

    if args.check_env and not args.cli:
        return _print_env_status(locator, config_mgr)

    if args.check_env and not args.source:
        return _print_env_status(locator, config_mgr)

    if not args.source:
        print("[ERROR] --source is required in --cli mode.", file=sys.stderr)
        return 2

    source_path = args.source.resolve()
    if not source_path.exists():
        print(f"[ERROR] Source path does not exist: {source_path}", file=sys.stderr)
        return 2

    if not env_status.is_ready_for_swap:
        _print_env_status(locator, config_mgr)
        print("[ERROR] Environment is not ready for swapping.", file=sys.stderr)
        return 1

    kit_dir = config_mgr.resolve_path(config.kit_dir)
    if not kit_dir.exists():
        print(f"[ERROR] Swap kit directory not found: {kit_dir}", file=sys.stderr)
        return 1

    engine = SwapEngine(env_status=env_status, kit_dir=kit_dir)
    detected = engine.inspect_mod(source_path)

    if args.origin:
        origin = SurvivorRegistry.get(args.origin).id
    elif detected.detected_origin is not None:
        origin = detected.detected_origin
        print(f"[INFO] Auto-detected origin survivor: {SurvivorRegistry.get(origin).display_name} ({origin.value})")
    else:
        print("[ERROR] Could not auto-detect origin survivor. Specify --origin explicitly.", file=sys.stderr)
        return 2

    if args.all_except_origin:
        destinations = [spec.id for spec in SurvivorRegistry.all() if spec.id != origin]
    elif args.dest:
        destinations = _parse_survivor_list(args.dest)
        destinations = [d for d in destinations if d != origin]
        if not destinations:
            print("[ERROR] Destination list contains no survivors distinct from the origin.", file=sys.stderr)
            return 2
    else:
        print("[ERROR] Specify --dest <survivor ...> or --all-except-origin.", file=sys.stderr)
        return 2

    metadata = ModMetadata(
        title=args.title if args.title is not None else detected.metadata.title,
        version=args.version if args.version is not None else detected.metadata.version,
        description=args.description if args.description is not None else detected.metadata.description,
        author=args.author if args.author is not None else detected.metadata.author,
        author_steam_id=detected.metadata.author_steam_id,
        url=detected.metadata.url,
        steam_app_id=detected.metadata.steam_app_id,
        extra_fields=dict(detected.metadata.extra_fields),
    )

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else config_mgr.resolve_path(config.output_dir)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    install_to_addons = bool(args.install or config.auto_install_to_addons)
    keep_temp = bool(args.keep_temp or config.keep_temp_on_error)

    request = SwapJobRequest(
        source_path=source_path,
        origin=origin,
        destinations=destinations,
        output_name_template=args.output_name,
        metadata=metadata,
        output_dir=output_dir,
        install_to_addons=install_to_addons,
        addons_dir=env_status.l4d2_addons_dir if install_to_addons else None,
        include_arms=not args.no_arms,
        include_vgui=not args.no_vgui,
        include_weapons=not args.no_weapons,
    )

    def on_progress(p: SwapProgress) -> None:
        prefix = f"[{p.percent:3d}%]"
        if p.target is not None:
            prefix += f" [{p.target.value}]"
        if p.log_line:
            print(f"{prefix} {p.log_line}")
        else:
            print(f"{prefix} {p.message}")

    results = engine.run_job(request, progress_cb=on_progress, keep_temp_on_error=keep_temp)

    print("\n=== Swap Summary ===")
    failed = 0
    for res in results:
        status_tag = "OK" if res.success else "FAIL"
        print(f"  [{status_tag}] {res.destination.value}: {res.vpk_path or res.error_message}")
        if res.installed_path:
            print(f"       Installed to: {res.installed_path}")
        for warn in res.warnings:
            print(f"       [WARN] {warn}")
        if not res.success:
            failed += 1

    return 0 if failed == 0 else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cli or args.check_env or args.apply_crowbar_settings:
        return _run_cli(args)

    try:
        from ui.main_window import launch_gui
    except ModuleNotFoundError as exc:
        msg = (
            f"Missing Python dependency: {exc.name}\n\n"
            "Double-click _INSTALL_REQUIREMENTS.bat or run this command first:\n"
            "pip install -r requirements.txt"
        )
        print(f"[ERROR] {msg}", file=sys.stderr)
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, msg, APP_META.name, 0x10)
        except Exception:
            pass
        return 1

    return launch_gui(project_root=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
