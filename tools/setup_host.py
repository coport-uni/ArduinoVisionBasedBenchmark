"""Host bootstrap: verify and install everything the harness needs.

One-time setup distinct from tools/preflight.py (the per-run gate).

Usage:
    python tools/setup_host.py --check          # report only
    python tools/setup_host.py --install       # install missing software
    python tools/setup_host.py --register-key  # push SSH pubkey to board
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config  # noqa: E402

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Run a command, returning (exit_code, combined_output)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except FileNotFoundError:
        return 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def _ssh_target(config) -> str:
    return f"{config['board_user']}@{config['board_ip']}"


def check_python() -> tuple[bool, str]:
    ok = sys.version_info >= (3, 10)
    return ok, f"Python {sys.version.split()[0]}"


def check_ffmpeg(config) -> tuple[bool, str]:
    code, out = _run([config["ffmpeg_path"], "-version"])
    return code == 0, out.splitlines()[0] if out else "missing"


def check_openssh(config) -> tuple[bool, str]:
    code, out = _run([config.get("ssh_path", "ssh"), "-V"])
    return code == 0, out or "missing"


def check_ssh_key_auth(config) -> tuple[bool, str]:
    code, out = _run(
        [config.get("ssh_path", "ssh"), *SSH_OPTS, _ssh_target(config), "true"],
        timeout=15,
    )
    return code == 0, "key auth OK" if code == 0 else out


def check_claude(config) -> tuple[bool, str]:
    code, out = _run([config["claude_path"], "--version"], timeout=30)
    return code == 0, out.splitlines()[0] if out else "missing"


def check_ruff() -> tuple[bool, str]:
    code, out = _run(["ruff", "--version"])
    return code == 0, out or "missing"


def check_gh() -> tuple[bool, str]:
    code, out = _run(["gh", "auth", "status"], timeout=30)
    return code == 0, "authenticated" if code == 0 else "not authenticated"


def check_jq() -> tuple[bool, str]:
    code, out = _run(["jq", "--version"])
    return code == 0, out or "missing"


def check_imaging() -> tuple[bool, str]:
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401

        return True, "Pillow + numpy importable"
    except ImportError as exc:
        return False, str(exc)


def check_host_camera(config) -> tuple[bool, str]:
    code, out = _run(
        [
            config["ffmpeg_path"],
            "-hide_banner",
            "-list_devices",
            "true",
            "-f",
            "dshow",
            "-i",
            "dummy",
        ],
        timeout=30,
    )
    # ffmpeg exits non-zero for -list_devices; inspect output instead.
    name = config["camera_device_name"]
    found = name.lower() in out.lower()
    return found, f'"{name}" {"found" if found else "NOT found"} in dshow list'


def check_board_reachable(config) -> tuple[bool, str]:
    ok, detail = check_ssh_key_auth(config)
    if ok:
        return True, "board reachable over SSH"
    return False, detail


def check_board_sudo(config) -> tuple[bool, str]:
    code, out = _run(
        [
            config.get("ssh_path", "ssh"),
            *SSH_OPTS,
            _ssh_target(config),
            "sudo -n true",
        ],
        timeout=15,
    )
    return code == 0, "passwordless sudo OK" if code == 0 else out


def check_board_camera(config) -> tuple[bool, str]:
    code, out = _run(
        [
            config.get("ssh_path", "ssh"),
            *SSH_OPTS,
            _ssh_target(config),
            "ls /dev/video* 2>/dev/null",
        ],
        timeout=15,
    )
    ok = code == 0 and out.strip() != ""
    return ok, out.strip() or "no /dev/video* on board"


def check_nvidia_smi() -> tuple[bool, str]:
    code, out = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,power.draw",
            "--format=csv,noheader",
        ]
    )
    return code == 0, out.replace("\n", " | ") if out else "missing"


def register_key(config) -> int:
    """Push the local SSH public key to the board's authorized_keys.

    Uses plink with the password from config.local.json exactly once;
    all later access is key-based. The password is passed via a temp
    file (-pwfile), never on the command line or in logs.
    """
    pub_path = Path.home() / ".ssh" / "id_ed25519.pub"
    if not pub_path.exists():
        print("no ~/.ssh/id_ed25519.pub -- run ssh-keygen first")
        return 1
    password = config.board_password
    if not password:
        print("board_password missing from config.local.json")
        return 1
    pubkey = pub_path.read_text(encoding="utf-8").strip()
    remote_cmd = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qF '{pubkey}' ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo '{pubkey}' >> ~/.ssh/authorized_keys; "
        "chmod 600 ~/.ssh/authorized_keys && echo REGISTERED"
    )
    # plink -batch refuses unknown host keys, so pin the fingerprint
    # OpenSSH already recorded in known_hosts.
    code, out = _run(["ssh-keygen", "-F", config["board_ip"], "-l"], timeout=15)
    fingerprint = None
    for token in out.split():
        if token.startswith("SHA256:"):
            fingerprint = token
            break
    if not fingerprint:
        print("board host key not in known_hosts -- ssh to the board once")
        return 1
    fd, pwfile = tempfile.mkstemp(prefix="bpw_", text=True)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(password)
        proc = subprocess.run(
            [
                "plink",
                "-ssh",
                "-batch",
                "-hostkey",
                fingerprint,
                "-pwfile",
                pwfile,
                _ssh_target(config),
                remote_cmd,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
        output = (proc.stdout + proc.stderr).strip()
    finally:
        os.unlink(pwfile)
    if "REGISTERED" in output:
        print("public key registered on board")
        ok, detail = check_ssh_key_auth(config)
        print(f"key auth verification: {detail}")
        return 0 if ok else 1
    print(f"registration failed: {output}")
    return 1


def setup_sudo(config) -> int:
    """Configure passwordless sudo for the board user (one-time).

    Pipes the password from config.local.json to `sudo -S` over the
    existing key-authenticated SSH session; the password never appears
    on a command line or in a log.
    """
    password = config.board_password
    if not password:
        print("board_password missing from config.local.json")
        return 1
    user = config["board_user"]
    sudoers_file = f"/etc/sudoers.d/010-{user}-nopasswd"
    remote_cmd = (
        "sudo -S -p '' sh -c "
        f"\"echo '{user} ALL=(ALL) NOPASSWD:ALL' > {sudoers_file} "
        f'&& chmod 440 {sudoers_file}" && echo SUDO_CONFIGURED'
    )
    proc = subprocess.run(
        [config.get("ssh_path", "ssh"), *SSH_OPTS, _ssh_target(config), remote_cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        input=password + "\n",
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if "SUDO_CONFIGURED" in output:
        ok, detail = check_board_sudo(config)
        print(f"passwordless sudo: {detail}")
        return 0 if ok else 1
    print(f"sudo setup failed: {output}")
    return 1


INSTALL_COMMANDS: dict[str, list[list[str]]] = {
    "ffmpeg": [
        [
            "winget",
            "install",
            "--id",
            "Gyan.FFmpeg",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    ],
    "ruff / Pillow / numpy": [
        [sys.executable, "-m", "pip", "install", "--user", "ruff", "pillow", "numpy"]
    ],
}


def run_checks(config) -> list[tuple[str, bool, str]]:
    """Run every host/board check and return (name, ok, detail) rows."""
    return [
        ("Python 3.10+", *check_python()),
        ("ffmpeg", *check_ffmpeg(config)),
        ("OpenSSH client", *check_openssh(config)),
        ("SSH key auth to board", *check_ssh_key_auth(config)),
        ("claude CLI", *check_claude(config)),
        ("ruff", *check_ruff()),
        ("gh CLI auth", *check_gh()),
        ("jq (hooks)", *check_jq()),
        ("Pillow + numpy", *check_imaging()),
        ("host camera (dshow)", *check_host_camera(config)),
        ("board reachable (SSH)", *check_board_reachable(config)),
        ("board passwordless sudo", *check_board_sudo(config)),
        ("board camera /dev/video*", *check_board_camera(config)),
        ("nvidia-smi (GLM only)", *check_nvidia_smi()),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only")
    parser.add_argument(
        "--install", action="store_true", help="install missing software"
    )
    parser.add_argument(
        "--register-key",
        action="store_true",
        help="register SSH public key on the board (uses password once)",
    )
    parser.add_argument(
        "--setup-sudo",
        action="store_true",
        help="configure passwordless sudo on the board (one-time)",
    )
    args = parser.parse_args()

    config = load_config()

    if args.register_key:
        return register_key(config)
    if args.setup_sudo:
        return setup_sudo(config)

    rows = run_checks(config)
    width = max(len(name) for name, _, _ in rows)
    print(f"{'check':<{width}}  result  detail")
    print("-" * (width + 40))
    for name, ok, detail in rows:
        print(f"{name:<{width}}  {'PASS' if ok else 'FAIL':<6}  {detail}")

    if args.install:
        for name, ok, _ in rows:
            key = name.split()[0].lower()
            for target, cmds in INSTALL_COMMANDS.items():
                if key in target.lower() and not ok:
                    for cmd in cmds:
                        print(f"installing {target}: {' '.join(cmd)}")
                        subprocess.run(cmd, check=False)

    # nvidia-smi is GLM-only: never fail a Claude-first bootstrap on it.
    hard_rows = [row for row in rows if "GLM only" not in row[0]]
    return 0 if all(ok for _, ok, _ in hard_rows) else 1


if __name__ == "__main__":
    sys.exit(main())
