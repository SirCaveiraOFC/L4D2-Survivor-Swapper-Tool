from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class SwapCancelledError(Exception):
    """Raised when the user cancels an active conversion, scan, or subprocess operation."""


class SurvivorId(str, Enum):
    """Canonical identifiers for all 8 Left 4 Dead survivors."""

    BILL = "bill"
    ZOEY = "zoey"
    LOUIS = "louis"
    FRANCIS = "francis"
    NICK = "nick"
    ROCHELLE = "rochelle"
    COACH = "coach"
    ELLIS = "ellis"


@dataclass(frozen=True)
class FpArmsFiles:
    """First-person viewmodel arms file names for a survivor."""

    dx90_vtx: str
    mdl: str
    vvd: str

    def all_filenames(self) -> tuple[str, ...]:
        return (self.dx90_vtx, self.mdl, self.vvd)


@dataclass(frozen=True)
class VguiIconFiles:
    """VGUI portrait texture file names for a survivor."""

    lobby_icon: str
    in_game_icon: str
    incap_icon: str

    def all_filenames(self) -> tuple[str, ...]:
        return (self.lobby_icon, self.in_game_icon, self.incap_icon)


@dataclass(frozen=True)
class SurvivorSpec:
    """Complete Source Engine asset metadata for a survivor."""

    id: SurvivorId
    display_name: str
    generation: str
    survivor_id: str
    model_file: str
    anims_folder: str
    kit_folder: str
    default_includemodels: tuple[str, ...]
    fp_arms: FpArmsFiles
    vgui: VguiIconFiles

    @property
    def qc_filename(self) -> str:
        return f"{self.survivor_id}.qc"

    @property
    def vrd_filename(self) -> str:
        return f"{self.survivor_id}.vrd"

    @property
    def vta_filename(self) -> str:
        return f"{self.survivor_id}_01.vta"

    @property
    def model_stem(self) -> str:
        return self.survivor_id


@dataclass
class ModMetadata:
    """Addon metadata parsed from or serialized to addoninfo.txt."""

    title: str = "Swapped Survivor Skin"
    version: str = "1.0"
    description: str = ""
    author: str = ""
    author_steam_id: str = ""
    url: str = ""
    steam_app_id: str = "550"
    extra_fields: dict[str, str] = field(default_factory=dict)
    original_title: str = ""


@dataclass
class DetectedModInfo:
    """Inspection summary for an input .vpk archive or extracted mod folder."""

    source_path: Path
    is_vpk: bool
    detected_origin: Optional[SurvivorId]
    has_arms: bool
    detected_arms_mdl: Optional[str]
    has_vgui: bool
    vgui_files: list[str]
    has_weapons: bool
    has_physics: bool
    metadata: ModMetadata
    file_list: list[str]
    light_models: list[str] = field(default_factory=list)

    @property
    def has_light_models(self) -> bool:
        return bool(self.light_models)


@dataclass
class EnvironmentStatus:
    """Verification report of Steam, L4D2, Authoring Tools, and Crowbar config."""

    steam_path: Optional[Path] = None
    steam_libraries: list[Path] = field(default_factory=list)
    l4d2_dir: Optional[Path] = None
    l4d2_gameinfo: Optional[Path] = None
    l4d2_addons_dir: Optional[Path] = None
    studiomdl_path: Optional[Path] = None
    vpk_exe_path: Optional[Path] = None
    decompiler_cli_path: Optional[Path] = None
    l4d2_installed: bool = False
    authoring_tools_installed: bool = False
    crowbar_settings_path: Optional[Path] = None
    crowbar_settings_exists: bool = False
    crowbar_settings_valid: bool = False
    crowbar_issues: list[str] = field(default_factory=list)

    @property
    def is_ready_for_swap(self) -> bool:
        return (
            self.l4d2_installed
            and self.l4d2_gameinfo is not None
            and self.l4d2_gameinfo.exists()
            and self.studiomdl_path is not None
            and self.studiomdl_path.exists()
            and self.vpk_exe_path is not None
            and self.vpk_exe_path.exists()
            and self.decompiler_cli_path is not None
            and self.decompiler_cli_path.exists()
        )


@dataclass
class AppConfig:
    """Persisted application preferences (settings.json)."""

    l4d2_dir: str = ""
    vpk_executable: str = ""
    studiomdl_executable: str = ""
    output_dir: str = "Swapped_Survivors"
    workshop_download_dir: str = "Workshop_Downloads"
    kit_dir: str = "HUNK'S_SURVIVOR_SWAP_KIT"
    auto_install_to_addons: bool = False
    keep_temp_on_error: bool = False
    first_run_completed: bool = False
    sanitize_origin_title: bool = True
    theme: str = "Dark"
    language: str = "auto"
    github_repo: str = ""
    auto_check_updates: bool = True


@dataclass
class SwapProgress:
    """Progress notification emitted during a swap pipeline run."""

    step: int
    total_steps: int
    percent: int
    message: str
    target: Optional[SurvivorId] = None
    log_line: Optional[str] = None


ProgressCallback = Callable[[SwapProgress], None]
CancelCallback = Callable[[], bool]


@dataclass
class InstalledAddonEntry:
    """Summary of an installed survivor mod .vpk inside L4D2 addons or workshop."""

    vpk_path: Path
    title: str
    author: str
    origin: Optional[SurvivorId]
    replaced_survivors: tuple[SurvivorId, ...] = ()
    source_kind: str = "addons"
    enabled_in_game: bool = True
    version: str = ""
    description: str = ""
    url: str = ""
    author_steam_id: str = ""
    tagline: str = ""
    file_size_bytes: int = 0
    has_arms: bool = False
    has_vgui: bool = False
    preview_bytes: Optional[bytes] = None


@dataclass
class AddonConflict:
    """Represents a survivor replacement overlap with an active installed VPK."""

    target_survivor: SurvivorId
    new_vpk_name: str
    existing_addon: InstalledAddonEntry


@dataclass
class SwapJobRequest:
    """User-configured conversion request for one or more target survivors."""

    source_path: Path
    origin: SurvivorId
    destinations: list[SurvivorId]
    output_name_template: str
    metadata: ModMetadata
    output_dir: Path
    install_to_addons: bool = False
    addons_dir: Optional[Path] = None
    include_arms: bool = True
    include_vgui: bool = True
    include_weapons: bool = True
    sanitize_origin_title: bool = True
    custom_addonimage_path: Optional[Path] = None


@dataclass
class SwapTargetResult:
    """Outcome of converting a mod for a single target survivor."""

    destination: SurvivorId
    success: bool
    vpk_path: Optional[Path] = None
    installed_path: Optional[Path] = None
    warnings: list[str] = field(default_factory=list)
    error_message: Optional[str] = None
    logs: list[str] = field(default_factory=list)
    cancelled: bool = False


@dataclass
class ConversionHistoryOutput:
    """Recorded output outcome for a single destination survivor inside a conversion job."""

    destination: str
    success: bool
    cancelled: bool = False
    vpk_path: str = ""
    error_message: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class ConversionHistoryEntry:
    """Persistent record of one completed, partial, or failed conversion run."""

    entry_id: str
    created_at: str
    mod_title: str
    author: str
    source_path: str
    origin: str
    destinations: list[str] = field(default_factory=list)
    output_dir: str = ""
    installed_to_addons: bool = False
    custom_cover_used: bool = False
    outputs: list[ConversionHistoryOutput] = field(default_factory=list)


@dataclass
class BatchQueueItem:
    """One queued mod entry in the Batch Swap workflow with optional per-item overrides."""

    item_id: str
    source_path: Path
    display_name: str
    detected_info: DetectedModInfo
    origin: Optional[SurvivorId]
    destinations: list[SurvivorId] = field(default_factory=list)
    use_global_destinations: bool = True
    use_global_options: bool = True
    output_name_template: str = ""
    metadata: ModMetadata = field(default_factory=ModMetadata)
    include_arms: bool = True
    include_vgui: bool = True
    include_weapons: bool = True
    install_to_addons: bool = False
    sanitize_origin_title: bool = True
    custom_addonimage_path: Optional[Path] = None
    original_cover_bytes: Optional[bytes] = None
    status: str = "pending"
    status_detail: str = ""
