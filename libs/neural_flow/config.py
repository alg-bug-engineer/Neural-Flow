from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Union

import yaml

from .models import RulesConfig


_INTERVAL_PATTERN = re.compile(r"^(\d+)([mh])$")


def load_rules(path: Union[str, Path]) -> RulesConfig:
    raw_text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text) or {}
    return RulesConfig.model_validate(data)


def rules_fingerprint(path: Union[str, Path]) -> str:
    raw = Path(path).read_bytes()
    return hashlib.sha256(raw).hexdigest()


def interval_to_seconds(interval_text: str) -> int:
    match = _INTERVAL_PATTERN.match(interval_text.strip().lower())
    if not match:
        raise ValueError(f"Unsupported interval format: {interval_text}")

    value = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return value * 60
    return value * 3600
