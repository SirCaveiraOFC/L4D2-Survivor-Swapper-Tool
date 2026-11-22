from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from core.models import CancelCallback, SwapCancelledError


def run_subprocess_cancellable(
    cmd: list[str],
    cwd: Optional[Path] = None,
    cancel_cb: Optional[CancelCallback] = None,
    timeout: float = 240.0,
) -> tuple[int, str, str]:
    """Execute a subprocess with live pipe draining, timeout enforcement, and cancel_cb termination."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        creationflags=creationflags,
    )
    out_chunks: list[str] = []
    err_chunks: list[str] = []

    def _drain(pipe, sink: list[str]) -> None:
        if pipe is None:
            return
        try:
            sink.append(pipe.read())
        except Exception:
            pass

    t_out = threading.Thread(target=_drain, args=(proc.stdout, out_chunks), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, err_chunks), daemon=True)
    t_out.start()
    t_err.start()

    deadline = time.monotonic() + timeout if timeout > 0 else None
    try:
        while True:
            ret = proc.poll()
            if ret is not None:
                break
            if cancel_cb is not None and cancel_cb():
                _terminate_process(proc)
                raise SwapCancelledError()
            if deadline is not None and time.monotonic() > deadline:
                _terminate_process(proc)
                raise RuntimeError(f"Subprocess timed out after {int(timeout)}s: {Path(cmd[0]).name}")
            time.sleep(0.1)
    finally:
        t_out.join(timeout=1.5)
        t_err.join(timeout=1.5)

    return proc.returncode or 0, "".join(out_chunks), "".join(err_chunks)


def _terminate_process(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=2.0)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except Exception:
            pass


class MdlToolchain:
    """Headless wrappers for MdlDecompilerCli.exe and Valve's studiomdl.exe."""

    def __init__(self, decompiler_cli: Path, studiomdl_exe: Path, l4d2_dir: Path) -> None:
        self.decompiler_cli = Path(decompiler_cli)
        self.studiomdl_exe = Path(studiomdl_exe)
        self.l4d2_dir = Path(l4d2_dir)
        self.active_cancel_cb: Optional[CancelCallback] = None

    def decompile(
        self,
        mdl_path: Path,
        output_dir: Path,
        cancel_cb: Optional[CancelCallback] = None,
    ) -> tuple[Path, list[str]]:
        """Decompile a compiled .mdl file into output_dir without GUI interaction."""
        if not self.decompiler_cli.exists():
            raise FileNotFoundError(f"MdlDecompilerCli.exe not found at: {self.decompiler_cli}")
        if not mdl_path.exists():
            raise FileNotFoundError(f"Input MDL file not found: {mdl_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        returncode, stdout, stderr = run_subprocess_cancellable(
            [str(self.decompiler_cli), "--input", str(mdl_path), "--output", str(output_dir)],
            cancel_cb=cancel_cb or self.active_cancel_cb,
        )
        logs = [line for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
        expected_qc = output_dir / f"{mdl_path.stem}.qc"

        if returncode != 0 or not expected_qc.exists():
            raise RuntimeError(
                f"Failed to decompile '{mdl_path.name}' (exit {returncode}):\n"
                + "\n".join(logs[-25:])
            )

        return expected_qc, logs

    @staticmethod
    def build_gameinfo_text(l4d2_dir: Path) -> str:
        """Build an isolated gameinfo.txt mounting |gameinfo_path|. ahead of L4D2 game archives."""
        search_folders = [
            l4d2_dir / "update",
            l4d2_dir / "left4dead2_dlc3",
            l4d2_dir / "left4dead2_dlc2",
            l4d2_dir / "left4dead2_dlc1",
            l4d2_dir / "left4dead2",
        ]
        search_lines = ["\t\t\tGame\t|gameinfo_path|."]
        for folder in search_folders:
            if folder.exists():
                escaped = str(folder).replace('"', "")
                search_lines.append(f'\t\t\tGame\t"{escaped}"')

        search_block = "\n".join(search_lines)
        return (
            '"GameInfo"\n'
            "{\n"
            '\tgame\t"L4D2 Swapper Staging"\n'
            "\tFileSystem\n"
            "\t{\n"
            "\t\tSteamAppId\t550\n"
            "\t\tSearchPaths\n"
            "\t\t{\n"
            f"{search_block}\n"
            "\t\t}\n"
            "\t}\n"
            "}\n"
        )

    def create_staging_game_dir(self, staging_game_dir: Path) -> Path:
        """Create an isolated Source game staging directory with gameinfo.txt for studiomdl.exe."""
        staging_game_dir.mkdir(parents=True, exist_ok=True)
        (staging_game_dir / "models" / "survivors").mkdir(parents=True, exist_ok=True)
        (staging_game_dir / "models" / "weapons" / "arms").mkdir(parents=True, exist_ok=True)

        (staging_game_dir / "gameinfo.txt").write_text(
            self.build_gameinfo_text(self.l4d2_dir),
            encoding="utf-8",
        )
        return staging_game_dir

    def compile_qc(
        self,
        qc_path: Path,
        staging_game_dir: Path,
        cancel_cb: Optional[CancelCallback] = None,
    ) -> list[str]:
        """Compile a .qc file using studiomdl.exe into the isolated staging_game_dir."""
        if not self.studiomdl_exe.exists():
            raise FileNotFoundError(f"studiomdl.exe not found at: {self.studiomdl_exe}")
        if not qc_path.exists():
            raise FileNotFoundError(f"QC file not found: {qc_path}")

        returncode, stdout, stderr = run_subprocess_cancellable(
            [
                str(self.studiomdl_exe),
                "-game",
                str(staging_game_dir),
                "-nop4",
                "-verbose",
                str(qc_path),
            ],
            cwd=qc_path.parent,
            cancel_cb=cancel_cb or self.active_cancel_cb,
        )
        logs = [line for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
        if returncode != 0:
            raise RuntimeError(
                f"studiomdl.exe failed compiling '{qc_path.name}' (exit {returncode}):\n"
                + "\n".join(logs[-30:])
            )
        return logs
