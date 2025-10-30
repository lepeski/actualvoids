"""Shared data models for withdrawal handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional


class WithdrawalStatus(str, Enum):
    """Lifecycle states of a withdrawal request."""

    PENDING = "pending"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(slots=True)
class WithdrawalRequest:
    """Representation of a withdrawal request."""

    id: Optional[int]
    player_name: str
    wallet_address: str
    amount: Decimal
    currency: str
    status: WithdrawalStatus
    created_at: datetime
    updated_at: datetime
    player_uuid: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    discord_message_id: Optional[int] = None
    approved_by: Optional[str] = None
    approved_by_id: Optional[int] = None
    transaction_id: Optional[str] = None
    failure_reason: Optional[str] = None

    def to_api_dict(self) -> Dict[str, Any]:
        """Serialize the request to a JSON-friendly representation."""

        return {
            "id": self.id,
            "player_name": self.player_name,
            "player_uuid": self.player_uuid,
            "wallet_address": self.wallet_address,
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "discord_message_id": self.discord_message_id,
            "approved_by": self.approved_by,
            "approved_by_id": self.approved_by_id,
            "transaction_id": self.transaction_id,
            "failure_reason": self.failure_reason,
        }


__all__ = ["WithdrawalStatus", "WithdrawalRequest"]
