"""Configuration helpers for the withdrawal bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


def _parse_int(value: str | None, *, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Expected integer but received {value!r}") from exc


def _parse_int_list(values: str | None) -> List[int]:
    if not values:
        return []
    result: List[int] = []
    for raw in values.split(","):
        raw = raw.strip()
        if not raw:
            continue
        result.append(_parse_int(raw) or 0)
    return result


@dataclass(slots=True)
class Settings:
    """Runtime configuration for the application."""

    discord_token: str
    withdrawal_channel_id: int
    admin_role_ids: List[int] = field(default_factory=list)
    guild_id: Optional[int] = None
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    database_path: str = "withdrawals.db"
    log_level: str = "INFO"
    wallet_provider: str = "auto"
    wallet_endpoint: Optional[str] = None
    wallet_api_key: Optional[str] = None
    piteas_api_url: Optional[str] = None
    piteas_api_key: Optional[str] = None
    piteas_project_id: Optional[str] = None
    piteas_wallet_id: Optional[str] = None
    piteas_asset_symbol: Optional[str] = None
    piteas_network: Optional[str] = None
    piteas_priority: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Settings":
        """Create :class:`Settings` using environment variables."""

        discord_token = os.getenv("DISCORD_TOKEN")
        if not discord_token:
            raise ValueError("DISCORD_TOKEN environment variable is required")

        withdrawal_channel_id = _parse_int(os.getenv("WITHDRAWAL_CHANNEL_ID"))
        if withdrawal_channel_id is None:
            raise ValueError("WITHDRAWAL_CHANNEL_ID environment variable is required")

        admin_role_ids = _parse_int_list(os.getenv("ADMIN_ROLE_IDS"))
        guild_id = _parse_int(os.getenv("HOME_GUILD_ID"))
        api_host = os.getenv("API_HOST", "0.0.0.0")
        api_port = _parse_int(os.getenv("API_PORT"), default=8080) or 8080
        database_path = os.getenv("DATABASE_PATH", "withdrawals.db")
        log_level = os.getenv("LOG_LEVEL", "INFO")
        wallet_provider = os.getenv("WALLET_PROVIDER", "auto").strip().lower()
        wallet_endpoint = os.getenv("WALLET_ENDPOINT")
        wallet_api_key = os.getenv("WALLET_API_KEY")
        piteas_api_url = os.getenv("PITEAS_API_URL")
        piteas_api_key = os.getenv("PITEAS_API_KEY")
        piteas_project_id = os.getenv("PITEAS_PROJECT_ID")
        piteas_wallet_id = os.getenv("PITEAS_WALLET_ID")
        piteas_asset_symbol = os.getenv("PITEAS_ASSET_SYMBOL")
        piteas_network = os.getenv("PITEAS_NETWORK")
        piteas_priority = os.getenv("PITEAS_PRIORITY")

        if wallet_provider not in {"auto", "piteas"}:
            raise ValueError(
                "WALLET_PROVIDER must be either 'auto' or 'piteas'"
            )

        if wallet_provider == "piteas":
            missing = [
                name
                for name, value in {
                    "PITEAS_API_KEY": piteas_api_key,
                    "PITEAS_PROJECT_ID": piteas_project_id,
                    "PITEAS_WALLET_ID": piteas_wallet_id,
                    "PITEAS_ASSET_SYMBOL": piteas_asset_symbol,
                    "PITEAS_NETWORK": piteas_network,
                }.items()
                if not value
            ]
            if missing:
                formatted = ", ".join(missing)
                raise ValueError(
                    "Piteas wallet provider selected but missing required env vars: "
                    f"{formatted}"
                )

        return cls(
            discord_token=discord_token,
            withdrawal_channel_id=withdrawal_channel_id,
            admin_role_ids=admin_role_ids,
            guild_id=guild_id,
            api_host=api_host,
            api_port=api_port,
            database_path=database_path,
            log_level=log_level,
            wallet_provider=wallet_provider,
            wallet_endpoint=wallet_endpoint,
            wallet_api_key=wallet_api_key,
            piteas_api_url=piteas_api_url,
            piteas_api_key=piteas_api_key,
            piteas_project_id=piteas_project_id,
            piteas_wallet_id=piteas_wallet_id,
            piteas_asset_symbol=piteas_asset_symbol,
            piteas_network=piteas_network,
            piteas_priority=piteas_priority,
        )

    def admin_role_set(self) -> set[int]:
        """Return the configured administrator role identifiers as a set."""

        return set(self.admin_role_ids)


__all__ = ["Settings"]
