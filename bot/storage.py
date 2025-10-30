"""SQLite persistence for withdrawal requests."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from .models import WithdrawalRequest, WithdrawalStatus


class WithdrawalNotFoundError(LookupError):
    """Raised when a withdrawal request cannot be located."""


class WithdrawalStateError(RuntimeError):
    """Raised when a withdrawal is in an unexpected state."""


class WithdrawalStore:
    """Lightweight SQLite-backed persistence layer."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._conn = sqlite3.connect(self._database_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT NOT NULL,
                player_uuid TEXT,
                wallet_address TEXT NOT NULL,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT,
                discord_message_id INTEGER,
                approved_by TEXT,
                approved_by_id INTEGER,
                transaction_id TEXT,
                failure_reason TEXT
            )
            """
        )
        self._conn.commit()

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
        """Persist a new withdrawal request."""

        payload = {
            "player_name": player_name,
            "player_uuid": player_uuid,
            "wallet_address": wallet_address,
            "amount": str(amount),
            "currency": currency,
            "status": WithdrawalStatus.PENDING.value,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "metadata": json.dumps(metadata or {}),
        }

        async with self._lock:
            row = await asyncio.to_thread(self._insert_row, payload)
        return self._row_to_request(row)

    async def set_discord_message(self, request_id: int, message_id: int) -> WithdrawalRequest:
        """Store the Discord message identifier for the request."""

        async with self._lock:
            row = await asyncio.to_thread(
                self._update_row,
                request_id,
                {"discord_message_id": message_id},
            )
        return self._row_to_request(row)

    async def get_request(self, request_id: int) -> WithdrawalRequest:
        async with self._lock:
            row = await asyncio.to_thread(self._get_row, request_id)
        if row is None:
            raise WithdrawalNotFoundError(f"Unknown request: {request_id}")
        return self._row_to_request(row)

    async def list_requests(
        self, *, status: Optional[WithdrawalStatus] = None, limit: int = 50
    ) -> List[WithdrawalRequest]:
        async with self._lock:
            rows = await asyncio.to_thread(self._select_rows, status, limit)
        return [self._row_to_request(row) for row in rows]

    async def mark_processing(self, request_id: int) -> WithdrawalRequest:
        async with self._lock:
            request = await asyncio.to_thread(self._get_row, request_id)
            if request is None:
                raise WithdrawalNotFoundError(f"Unknown request: {request_id}")
            model = self._row_to_request(request)
            if model.status is not WithdrawalStatus.PENDING:
                raise WithdrawalStateError(
                    f"Cannot move request {request_id} to processing from {model.status.value}"
                )
            updated = await asyncio.to_thread(
                self._update_row,
                request_id,
                {"status": WithdrawalStatus.PROCESSING.value},
            )
        return self._row_to_request(updated)

    async def mark_approved(
        self,
        request_id: int,
        *,
        admin_name: str,
        admin_id: int,
        transaction_id: str,
    ) -> WithdrawalRequest:
        async with self._lock:
            request = await asyncio.to_thread(self._get_row, request_id)
            if request is None:
                raise WithdrawalNotFoundError(f"Unknown request: {request_id}")
            model = self._row_to_request(request)
            if model.status not in {WithdrawalStatus.PENDING, WithdrawalStatus.PROCESSING}:
                raise WithdrawalStateError(
                    f"Cannot approve request {request_id} from {model.status.value}"
                )
            updated = await asyncio.to_thread(
                self._update_row,
                request_id,
                {
                    "status": WithdrawalStatus.APPROVED.value,
                    "approved_by": admin_name,
                    "approved_by_id": admin_id,
                    "transaction_id": transaction_id,
                    "failure_reason": None,
                },
            )
        return self._row_to_request(updated)

    async def mark_rejected(
        self,
        request_id: int,
        *,
        admin_name: str,
        admin_id: int,
        reason: Optional[str],
    ) -> WithdrawalRequest:
        async with self._lock:
            request = await asyncio.to_thread(self._get_row, request_id)
            if request is None:
                raise WithdrawalNotFoundError(f"Unknown request: {request_id}")
            model = self._row_to_request(request)
            if model.status not in {WithdrawalStatus.PENDING, WithdrawalStatus.PROCESSING}:
                raise WithdrawalStateError(
                    f"Cannot reject request {request_id} from {model.status.value}"
                )
            updated = await asyncio.to_thread(
                self._update_row,
                request_id,
                {
                    "status": WithdrawalStatus.REJECTED.value,
                    "approved_by": admin_name,
                    "approved_by_id": admin_id,
                    "failure_reason": reason,
                },
            )
        return self._row_to_request(updated)

    async def mark_failed(self, request_id: int, reason: str) -> WithdrawalRequest:
        async with self._lock:
            request = await asyncio.to_thread(self._get_row, request_id)
            if request is None:
                raise WithdrawalNotFoundError(f"Unknown request: {request_id}")
            updated = await asyncio.to_thread(
                self._update_row,
                request_id,
                {
                    "status": WithdrawalStatus.FAILED.value,
                    "failure_reason": reason,
                },
            )
        return self._row_to_request(updated)

    async def cleanup(self) -> None:
        """Close the underlying database connection."""

        async with self._lock:
            await asyncio.to_thread(self._conn.close)

    # Internal helpers -------------------------------------------------

    def _insert_row(self, payload: Dict[str, object]) -> sqlite3.Row:
        placeholders = ", ".join(payload.keys())
        values_placeholders = ", ".join(["?"] * len(payload))
        values = list(payload.values())
        cursor = self._conn.execute(
            f"INSERT INTO withdrawals ({placeholders}) VALUES ({values_placeholders})",
            values,
        )
        self._conn.commit()
        return self._get_row(cursor.lastrowid)

    def _get_row(self, request_id: int) -> Optional[sqlite3.Row]:
        cursor = self._conn.execute(
            "SELECT * FROM withdrawals WHERE id = ?", (request_id,)
        )
        return cursor.fetchone()

    def _select_rows(
        self, status: Optional[WithdrawalStatus], limit: int
    ) -> Sequence[sqlite3.Row]:
        if status is None:
            cursor = self._conn.execute(
                "SELECT * FROM withdrawals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT * FROM withdrawals
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status.value, limit),
            )
        return cursor.fetchall()

    def _update_row(self, request_id: int, fields: Dict[str, object]) -> sqlite3.Row:
        if not fields:
            raise ValueError("No fields provided for update")
        assignments = []
        values: List[object] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(request_id)
        sql = f"UPDATE withdrawals SET {', '.join(assignments)} WHERE id = ?"
        cursor = self._conn.execute(sql, values)
        if cursor.rowcount == 0:
            raise WithdrawalNotFoundError(f"Unknown request: {request_id}")
        self._conn.commit()
        return self._get_row(request_id)

    def _row_to_request(self, row: sqlite3.Row) -> WithdrawalRequest:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        return WithdrawalRequest(
            id=row["id"],
            player_name=row["player_name"],
            player_uuid=row["player_uuid"],
            wallet_address=row["wallet_address"],
            amount=Decimal(row["amount"]),
            currency=row["currency"],
            status=WithdrawalStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=metadata,
            discord_message_id=row["discord_message_id"],
            approved_by=row["approved_by"],
            approved_by_id=row["approved_by_id"],
            transaction_id=row["transaction_id"],
            failure_reason=row["failure_reason"],
        )


__all__ = [
    "WithdrawalStore",
    "WithdrawalNotFoundError",
    "WithdrawalStateError",
]
