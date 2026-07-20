"""Typed configuration loader.

Loads config.json plus the gitignored config.local.json overlay
(secrets such as the board password). Undecided experiment values
stay externalized here per SPEC 4 and 10 -- never hardcode them.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from harness.errors import ConfigError

# Condition IDs from SPEC 1.2, in Latin-square round order.
LATIN_SQUARE_ROUNDS: list[list[str]] = [
    ["CLD_VP", "GLM_VP", "CLD_VM", "GLM_VM"],
    ["GLM_VP", "CLD_VM", "GLM_VM", "CLD_VP"],
    ["CLD_VM", "GLM_VM", "CLD_VP", "GLM_VP"],
]

ALL_CONDITIONS = ("CLD_VP", "CLD_VM", "GLM_VP", "GLM_VM")
TASKS = ("T1", "T2")

REQUIRED_KEYS = (
    "board_ip",
    "board_user",
    "ffmpeg_path",
    "camera_device_name",
    "claude_path",
    "timeout_s",
    "poll_interval_s",
    "post_exit_grace_s",
    "monitor_interval_s",
    "enabled_conditions",
    "led_regions",
    "hue_thresholds",
    "ha",
    "t2",
    "models",
    "claude_pricing_per_mtok",
)


@dataclass
class ConditionSpec:
    """One experiment condition (model x vision feedback)."""

    condition_id: str
    model: str
    vision: str  # "V+" or "V-"

    @classmethod
    def parse(cls, condition_id: str) -> "ConditionSpec":
        """Build a ConditionSpec from an ID such as CLD_VP."""
        model_code, vision_code = condition_id.split("_")
        model = {"CLD": "claude", "GLM": "glm"}[model_code]
        vision = {"VP": "V+", "VM": "V-"}[vision_code]
        return cls(condition_id=condition_id, model=model, vision=vision)


@dataclass
class TrialSpec:
    """One trial: task x condition x repetition."""

    task: str
    condition: ConditionSpec
    rep: int

    @property
    def trial_id(self) -> str:
        return f"{self.task}_{self.condition.condition_id}_r{self.rep}"


@dataclass
class Config:
    """Validated harness configuration."""

    raw: dict = field(repr=False)
    root: Path = field(repr=False)

    def __getitem__(self, key: str):
        return self.raw[key]

    def get(self, key: str, default=None):
        return self.raw.get(key, default)

    @property
    def board_password(self) -> str | None:
        """Board password from config.local.json; never log this."""
        return self.raw.get("board_password")

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"


def load_config(root: Path | None = None) -> Config:
    """Load and validate config.json (+ config.local.json overlay).

    @param root  Repository root; defaults to the package parent.
    @return      Config with the local overlay merged in.
    """
    root = root or Path(__file__).resolve().parent.parent
    main_path = root / "config.json"
    if not main_path.exists():
        raise ConfigError(f"config.json not found at {main_path}")
    try:
        raw = json.loads(main_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json is not valid JSON: {exc}") from exc

    local_path = root / "config.local.json"
    if local_path.exists():
        try:
            raw.update(json.loads(local_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"config.local.json is not valid JSON: {exc}") from exc

    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise ConfigError(f"config.json missing required keys: {missing}")

    for cond in raw["enabled_conditions"]:
        if cond not in ALL_CONDITIONS:
            raise ConfigError(f"unknown condition in enabled_conditions: {cond}")

    for name, region in raw["led_regions"].items():
        if len(region) != 4 or region[0] >= region[2] or region[1] >= region[3]:
            raise ConfigError(f"led_regions.{name} must be [x1, y1, x2, y2]")

    return Config(raw=raw, root=root)


def build_trial_matrix(config: Config, reps: int = 3) -> list[TrialSpec]:
    """Return trials in Latin-square order, filtered to enabled conditions.

    Disabled conditions (e.g. GLM while deferred) are removed while the
    relative order of the remaining cells is preserved -- the square is
    never reindexed.
    """
    enabled = set(config["enabled_conditions"])
    trials: list[TrialSpec] = []
    for rep_index, round_order in enumerate(LATIN_SQUARE_ROUNDS[:reps], 1):
        for condition_id in round_order:
            if condition_id not in enabled:
                continue
            for task in TASKS:
                trials.append(
                    TrialSpec(
                        task=task,
                        condition=ConditionSpec.parse(condition_id),
                        rep=rep_index,
                    )
                )
    return trials
