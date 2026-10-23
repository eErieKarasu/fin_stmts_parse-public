import os
import re
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml


CONFIG_PACKAGE = "fin_stmts_parse.config"
ENV_PACKAGE = f"{CONFIG_PACKAGE}.env"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
MAPPINGS_DIR = CONFIG_DIR / "mappings"


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_yaml_resource(package: str, filename: str) -> Dict[str, Any]:
    with resources.files(package).joinpath(filename).open("rb") as file_obj:
        return yaml.safe_load(file_obj)


def load_config(config_path: str) -> Dict[str, Any]:
    directory = os.path.dirname(config_path).replace("/", ".")
    filename = os.path.basename(config_path)
    return load_yaml_resource(directory, filename)


def load_env_config(env: Optional[str] = None) -> Dict[str, Any]:
    target_env = env or os.getenv("RUNNING_ENV", "local")
    return _expand_env(load_yaml_resource(ENV_PACKAGE, f"{target_env}.yaml"))


def _expand_env(value):
    """Resolve ${NAME:-default} without changing the existing config structure."""
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}",
            lambda match: os.getenv(match[1]) or match[2] or "",
            value,
        )
    return value


def get_mapping_config_paths(
    statement_type: str,
    consolidated: bool = False,
) -> Tuple[str, str]:
    variant = "consolidated" if consolidated else "standalone"
    config_dir = MAPPINGS_DIR / statement_type / variant
    return (
        str(config_dir / "semantic.yaml"),
        str(config_dir / "view.yaml"),
    )


if __name__ == "__main__":
    env = os.getenv("RUNNING_ENV", "local")
    print(env)
    load_env_config(env)
    print("Configuration loaded; values are not printed.")
