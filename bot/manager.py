"""High-level orchestration for withdrawal requests."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Awaitable, Callable, Dict, List, Optional

from .models import WithdrawalRequest, WithdrawalStatus
from .storage import (
    WithdrawalNotFoundError,
    WithdrawalStateError,
    WithdrawalStore,
)
from .wallet import WalletClient, WalletError

Logger = logging.Logger
NewRequestListener = Callable[[WithdrawalRequest], Awaitable[None] | None]


class WithdrawalManager:
    """Coordinate storage, wallet calls, and Discord notifications."""

    def __init__(self, store: WithdrawalStore, wallet: WalletClient, *, logger: Optional[Logger] = None) -> None:
        self.store = store
        self.wallet = wallet
        self._listeners: List[NewRequestListener] = []
        self._logger = logger or logging.getLogger(__name__)
        self._listener_lock = asyncio.Lock()

    def add_listener(self, listener: NewRequestListener) -> None:
        self._listeners.append(listener)

    async def create_request(
        self,
        *,
        player_name: str,
        wallet_address: str,
        amount: Decimal,
        currency: str,
        player_uuid: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> WithdrawalRequest:
        request = await self.store.create_request(
            player_name=player_name,
            wallet_address=wallet_address,
            amount=amount,
            currency=currency,
            player_uuid=player_uuid,
            metadata=metadata,
        )
        await self._notify_new_request(request)
        return request

    async def attach_message(self, request_id: int, message_id: int) -> WithdrawalRequest:
        return await self.store.set_discord_message(request_id, message_id)

    async def approve_request(self, request_id: int, *, admin_name: str, admin_id: int) -> WithdrawalRequest:
        processing = await self.store.mark_processing(request_id)
        try:
            transaction_id = await self.wallet.send_payment(processing)
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.exception("Wallet transfer failed for request %s", request_id)
            await self.store.mark_failed(request_id, str(exc))
            raise WalletError("Wallet transfer failed") from exc
        approved = await self.store.mark_approved(
            request_id,
            admin_name=admin_name,
            admin_id=admin_id,
            transaction_id=transaction_id,
        )
        return approved

    async def reject_request(
        self,
        request_id: int,
        *,
        admin_name: str,
        admin_id: int,
        reason: Optional[str] = None,
    ) -> WithdrawalRequest:
        return await self.store.mark_rejected(
            request_id,
            admin_name=admin_name,
            admin_id=admin_id,
            reason=reason,
        )

    async def list_pending(self, *, limit: int = 50) -> List[WithdrawalRequest]:
        return await self.store.list_requests(status=WithdrawalStatus.PENDING, limit=limit)

    async def get_request(self, request_id: int) -> WithdrawalRequest:
        return await self.store.get_request(request_id)

    async def _notify_new_request(self, request: WithdrawalRequest) -> None:
        async with self._listener_lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                result = listener(request)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pragma: no cover - log only
                self._logger.exception("Failed to deliver withdrawal notification")


__all__ = ["WithdrawalManager", "WithdrawalNotFoundError", "WithdrawalStateError"]
