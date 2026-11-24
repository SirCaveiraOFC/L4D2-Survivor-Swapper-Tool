from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppMetadataInfo:
    """Canonical application identity and semantic version (Major.Minor.Patch)."""

    name: str = "L4D2 Survivor Swapper Tool"
    major: int = 2
    minor: int = 1
    patch: int = 0
    developer: str = "Sr.Caveira"
    license_name: str = "PolyForm Noncommercial 1.0.0"
    github_repo: str = "SirCaveiraOFC/L4D2-Survivor-Swapper-Tool"
    github_branch: str = "main"
    toolchain_summary: str = "Headless StudioMDL + MdlDecompilerCli (Crowbar 0.74 Core)"
    credits: tuple[str, ...] = (
        "Sr.Caveira — Creator, Architecture & Automation",
        "ZeqMacaw — Crowbar 0.74 Decompiler Core",
        "H.U.N.K — Survivor Swap Kit Templates",
        "Valve Corporation — Source SDK (studiomdl & vpk)",
    )

    @property
    def version(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def version_tag(self) -> str:
        return f"v{self.version}"

    @property
    def window_title(self) -> str:
        return f"{self.name}  |  {self.version_tag}"

    @property
    def github_url(self) -> str:
        cleaned = (self.github_repo or "").strip().strip("/")
        if not cleaned:
            return ""
        if cleaned.lower().startswith(("https://", "http://")):
            return cleaned
        return f"https://github.com/{cleaned}"


APP_META = AppMetadataInfo()
