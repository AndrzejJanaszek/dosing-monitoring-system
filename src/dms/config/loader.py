import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ValidationError

from dms.config.models import AcquisitionConfig, SharedConfig, validate_acquisition_rules

CONFIG_DIR_VARIABLE = "DMS_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path("/etc/dms")
SHARED_FILE_NAME = "shared.toml"
ACQUISITION_FILE_NAME = "acquisition.toml"


class ConfigError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def resolve_config_dir() -> Path:
    return Path(os.environ.get(CONFIG_DIR_VARIABLE, DEFAULT_CONFIG_DIR))


def load_shared(config_dir: Path | None = None) -> SharedConfig:
    return _load(SHARED_FILE_NAME, SharedConfig, config_dir)


def load_acquisition(config_dir: Path | None = None) -> AcquisitionConfig:
    config = _load(ACQUISITION_FILE_NAME, AcquisitionConfig, config_dir)
    rule_errors = validate_acquisition_rules(config)
    if rule_errors:
        raise ConfigError([f"{ACQUISITION_FILE_NAME}: {error}" for error in rule_errors])
    return config


def _load[M: BaseModel](file_name: str, model: type[M], config_dir: Path | None) -> M:
    directory = config_dir if config_dir is not None else resolve_config_dir()
    path = directory / file_name
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{file_name}: file not found: {path}"]) from None
    except OSError as error:
        raise ConfigError([f"{file_name}: cannot read {path}: {error.strerror}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ConfigError([f"{file_name}: invalid TOML: {error}"]) from None
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(
            [
                f"{file_name}: {_format_location(item['loc'])}: {item['msg']}"
                for item in error.errors()
            ]
        ) from None


def _format_location(location: tuple[int | str, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path
