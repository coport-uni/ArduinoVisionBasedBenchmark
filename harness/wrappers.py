"""Per-trial wrapper generators: ssh.bat, scp.bat, snap.bat.

The wrappers sit first on the agent's PATH so every board access and
snapshot request is logged with a timestamp before delegating to the
real tool. snap.bat exists only in V+ trials (SPEC 1.3); its actual
work happens in harness.snap_cli so the batch file stays a thin shim.
"""

import shutil
import subprocess
import sys
from pathlib import Path

# %~dp0 is the wrapper dir; logs live next to the wrappers inside the
# trial folder. %* forwards all arguments; %ERRORLEVEL% is propagated.
_CALL_WRAPPER_TEMPLATE = """@echo off
setlocal enabledelayedexpansion
set "LOGFILE=%~dp0{log_name}"
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command ^
 "Get-Date -Format o"`) do set "TS=%%t"
>> "%LOGFILE%" echo !TS! {tool} %*
"{real_tool}" %*
exit /b %ERRORLEVEL%
"""

_SNAP_TEMPLATE = """@echo off
setlocal enabledelayedexpansion
set "LOGFILE=%~dp0snap_calls.log"
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command ^
 "Get-Date -Format o"`) do set "TS=%%t"
>> "%LOGFILE%" echo !TS! snap %*
"{python}" -m harness.snap_cli --trial-dir "{trial_dir}" --repo "{repo}"
exit /b %ERRORLEVEL%
"""


def _resolve(tool: str) -> str:
    """Absolute path of a host tool; wrappers must never self-recurse."""
    path = shutil.which(tool)
    if path is None:
        raise FileNotFoundError(f"required tool not on PATH: {tool}")
    return path


# Git Bash (the claude CLI Bash tool) does not resolve .bat files on
# PATH, so every wrapper is emitted twice: a .bat for cmd/PowerShell
# and an extensionless POSIX script for bash. Both log to the same
# file. $(cygpath -u ...) is unnecessary -- Git Bash runs Windows
# executables from absolute Windows paths directly.
_SH_CALL_WRAPPER_TEMPLATE = """#!/bin/sh
LOGFILE="$(dirname "$0")/{log_name}"
printf '%s {tool} %s\\n' "$(date -Iseconds)" "$*" >> "$LOGFILE"
exec "{real_tool}" "$@"
"""

_SH_SNAP_TEMPLATE = """#!/bin/sh
LOGFILE="$(dirname "$0")/snap_calls.log"
printf '%s snap %s\\n' "$(date -Iseconds)" "$*" >> "$LOGFILE"
exec "{python}" -m harness.snap_cli --trial-dir "{trial_dir}" --repo "{repo}"
"""


def generate_wrappers(trial_dir: Path, vision: str, config, repo_root: Path) -> Path:
    """Create the wrapper directory for one trial.

    @param trial_dir  Trial output folder; wrappers/ is created inside.
    @param vision     "V+" or "V-"; snap.bat exists only for V+.
    @param config     Harness config (paths).
    @param repo_root  Repository root, for `python -m harness.snap_cli`.
    @return           The wrapper directory to prepend to PATH.
    """
    wrapper_dir = trial_dir / "wrappers"
    wrapper_dir.mkdir(parents=True, exist_ok=True)

    for tool, log_name in (("ssh", "ssh_calls.log"), ("scp", "scp_calls.log")):
        real = _resolve(config.get(f"{tool}_path", tool))
        (wrapper_dir / f"{tool}.bat").write_text(
            _CALL_WRAPPER_TEMPLATE.format(log_name=log_name, tool=tool, real_tool=real),
            encoding="ascii",
        )
        sh_path = wrapper_dir / tool
        sh_path.write_text(
            _SH_CALL_WRAPPER_TEMPLATE.format(
                log_name=log_name, tool=tool, real_tool=real.replace("\\", "/")
            ),
            encoding="ascii",
            newline="\n",
        )

    if vision == "V+":
        (wrapper_dir / "snap.bat").write_text(
            _SNAP_TEMPLATE.format(
                python=sys.executable,
                trial_dir=str(trial_dir),
                repo=str(repo_root),
            ),
            encoding="ascii",
        )
        (wrapper_dir / "snap").write_text(
            _SH_SNAP_TEMPLATE.format(
                python=str(sys.executable).replace("\\", "/"),
                trial_dir=str(trial_dir).replace("\\", "/"),
                repo=str(repo_root).replace("\\", "/"),
            ),
            encoding="ascii",
            newline="\n",
        )
    return wrapper_dir


def count_calls(trial_dir: Path, log_name: str) -> int:
    """Line count of a wrapper log (FR6 call metrics); 0 when absent."""
    log_path = trial_dir / "wrappers" / log_name
    if not log_path.exists():
        return 0
    with log_path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if line.strip())


def smoke_test_wrapper(wrapper_dir: Path, tool: str = "ssh") -> bool:
    """Run a wrapper with a harmless flag to confirm logging works."""
    proc = subprocess.run(
        [str(wrapper_dir / f"{tool}.bat"), "-V"],
        capture_output=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    log_name = f"{tool}_calls.log"
    return proc.returncode == 0 and (wrapper_dir / log_name).exists()
