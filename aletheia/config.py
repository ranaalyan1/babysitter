from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class Config:
    provider_url: str = "http://127.0.0.1:11434/v1"
    api_key_env: str = "ALETHEIA_PROVIDER_API_KEY"
    model: str = "qwen2.5-coder:7b"
    stronger_model: str | None = None
    test_command: list[str] = field(default_factory=list)
    typecheck_command: list[str] = field(default_factory=list)
    command_timeout: float = 120
    provider_timeout: float = 120
    max_attempts: int = 6
    escalation_after: int = 2
    max_tool_rounds: int = 12
    allow_managed_tools: bool = False
    max_snapshot_bytes: int = 25_000_000
    max_output_bytes: int = 64_000
    token_env: str = "ALETHEIA_LOCAL_TOKEN"

    @classmethod
    def load(cls, root: Path) -> Config:
        path = root / "aletheia.json"
        if path.exists():
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("aletheia.json must contain a JSON object")
            unknown = data.keys() - cls.__dataclass_fields__.keys()
            if unknown:
                raise ValueError("Unknown configuration fields: " + ", ".join(sorted(unknown)))
            config = cls(**data)
        else:
            config = cls()
        config.validate()
        return config

    def validate(self) -> None:
        for name in ("provider_url", "model", "api_key_env", "token_env"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
                raise ValueError(f"{name} must be a nonempty string without control characters")
        if self.stronger_model is not None and (not isinstance(self.stronger_model, str) or not self.stronger_model.strip()):
            raise ValueError("stronger_model must be a nonempty string or null")
        for name in ("api_key_env", "token_env"):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", getattr(self, name)):
                raise ValueError(f"{name} must name an environment variable")
        url = urlparse(self.provider_url)
        try:
            url.port
        except ValueError as exc:
            raise ValueError("provider_url has an invalid port") from exc
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("provider_url must be an HTTP(S) base URL without embedded credentials/query")
        for command in (self.test_command, self.typecheck_command):
            if not isinstance(command, list) or any(not isinstance(x, str) or not x or "\x00" in x for x in command):
                raise ValueError("verification commands must be JSON argv arrays (no shell strings)")
        if not isinstance(self.allow_managed_tools, bool):
            raise ValueError("allow_managed_tools must be boolean")
        for name in ("command_timeout", "provider_timeout", "max_attempts", "escalation_after", "max_tool_rounds", "max_snapshot_bytes", "max_output_bytes"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        for name in ("max_attempts", "escalation_after", "max_tool_rounds", "max_snapshot_bytes", "max_output_bytes"):
            if not isinstance(getattr(self, name), int):
                raise ValueError(f"{name} must be an integer")

    def save(self, root: Path) -> None:
        self.validate()
        (root / "aletheia.json").write_text(json.dumps(asdict(self), indent=2) + "\n")
