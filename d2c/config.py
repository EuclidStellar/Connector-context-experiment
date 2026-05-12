from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field


class MerchantConfig(BaseModel):
    """Per-merchant configuration. Loaded from <merchant>/config.yaml + <merchant>/.env.

    Secrets live in .env (gitignored). Non-secret config in config.yaml.
    Connector-specific config is kept as a raw dict; each connector validates its own slice.
    """

    merchant_id: str
    merchant_name: str
    timezone: str = "Asia/Kolkata"
    base_currency: str = "INR"
    connectors: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ingestion: dict[str, Any] = Field(default_factory=dict)
    raw_lake: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load(cls, merchant_dir: Path) -> "MerchantConfig":
        config_path = merchant_dir / "config.yaml"
        env_path = merchant_dir / ".env"

        raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
        secrets = {k: v for k, v in dotenv_values(env_path).items() if v}
        raw["secrets"] = secrets
        return cls(**raw)

    def secret(self, key: str) -> str:
        if key not in self.secrets:
            raise KeyError(
                f"Required secret {key!r} not set for merchant {self.merchant_id!r}"
            )
        return self.secrets[key]
