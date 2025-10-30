"""Wallet client abstractions."""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Optional
from uuid import uuid4

import aiohttp
from yarl import URL

from .models import WithdrawalRequest


class WalletError(RuntimeError):
    """Raised when the wallet client fails to complete a withdrawal."""


class WalletClient(abc.ABC):
    """Abstract base class for cryptocurrency wallet integrations."""

    @abc.abstractmethod
    async def send_payment(self, request: WithdrawalRequest) -> str:
        """Send a payment for the given request and return the transaction identifier."""


class DummyWalletClient(WalletClient):
    """A stand-in wallet implementation that simulates transfers."""

    def __init__(self, *, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    async def send_payment(self, request: WithdrawalRequest) -> str:
        await asyncio.sleep(0.25)
        transaction_id = f"dummy-{uuid4()}"
        self._logger.info(
            "Simulated payout for request %s (%s %s) -> %s",
            request.id,
            request.amount,
            request.currency,
            transaction_id,
        )
        return transaction_id


class HTTPWalletClient(WalletClient):
    """HTTP-based wallet client that calls an external payout endpoint."""

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if not endpoint:
            raise ValueError("Wallet endpoint must be provided")
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout
        self._logger = logger or logging.getLogger(__name__)

    async def send_payment(self, request: WithdrawalRequest) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "request_id": request.id,
            "player_name": request.player_name,
            "wallet_address": request.wallet_address,
            "amount": str(request.amount),
            "currency": request.currency,
            "metadata": request.metadata,
        }

        timeout = aiohttp.ClientTimeout(total=self._timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._endpoint, json=payload, headers=headers) as response:
                    if response.status >= 400:
                        body = await response.text()
                        raise WalletError(
                            f"Wallet request failed with status {response.status}: {body.strip()}"
                        )
                    data = await response.json(content_type=None)
        except aiohttp.ClientError as exc:  # pragma: no cover - network failures
            raise WalletError("Failed to contact wallet endpoint") from exc

        transaction_id = (
            data.get("transaction_id")
            or data.get("txid")
            or data.get("id")
        )
        if not transaction_id:
            raise WalletError("Wallet response missing transaction identifier")

        transaction_id = str(transaction_id)
        self._logger.info(
            "Wallet payout completed for request %s -> %s",
            request.id,
            transaction_id,
        )
        return transaction_id


class PiteasWalletClient(WalletClient):
    """Wallet client that talks to a self-hosted Piteas API instance."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        project_id: str,
        wallet_id: str,
        asset_symbol: str,
        network: str,
        priority: Optional[str] = None,
        timeout: float = 30.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if not base_url:
            raise ValueError("Piteas base URL must be provided")
        if not api_key:
            raise ValueError("Piteas API key must be provided")
        if not project_id:
            raise ValueError("Piteas project ID must be provided")
        if not wallet_id:
            raise ValueError("Piteas wallet ID must be provided")
        if not asset_symbol:
            raise ValueError("Piteas asset symbol must be provided")
        if not network:
            raise ValueError("Piteas network must be provided")

        base = URL(base_url)
        if not base.scheme:
            raise ValueError("Piteas base URL must include a scheme (e.g. https://)")

        self._endpoint = base / "api" / "projects" / project_id / "wallets" / wallet_id / "withdrawals"
        self._api_key = api_key
        self._asset_symbol = asset_symbol
        self._network = network
        self._priority = priority
        self._timeout = timeout
        self._logger = logger or logging.getLogger(__name__)

    async def send_payment(self, request: WithdrawalRequest) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        payload = {
            "address": request.wallet_address,
            "amount": str(request.amount),
            "asset": self._asset_symbol,
            "network": self._network,
            "externalId": request.id,
            "playerName": request.player_name,
        }

        if request.metadata:
            payload["metadata"] = request.metadata
            memo = request.metadata.get("memo")
            if memo:
                payload["memo"] = memo

        if self._priority:
            payload["priority"] = self._priority

        timeout = aiohttp.ClientTimeout(total=self._timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(str(self._endpoint), json=payload, headers=headers) as response:
                    if response.status >= 400:
                        body = await response.text()
                        raise WalletError(
                            f"Piteas wallet request failed with status {response.status}: {body.strip()}"
                        )
                    data = await response.json(content_type=None)
        except aiohttp.ClientError as exc:  # pragma: no cover - network failures
            raise WalletError("Failed to contact Piteas wallet endpoint") from exc

        transaction_id = (
            data.get("transactionHash")
            or data.get("transaction_id")
            or data.get("txid")
            or data.get("id")
        )
        if not transaction_id:
            raise WalletError("Piteas response missing transaction identifier")

        transaction_id = str(transaction_id)
        self._logger.info(
            "Piteas payout completed for request %s -> %s",
            request.id,
            transaction_id,
        )
        return transaction_id


__all__ = [
    "WalletClient",
    "WalletError",
    "DummyWalletClient",
    "HTTPWalletClient",
    "PiteasWalletClient",
]
