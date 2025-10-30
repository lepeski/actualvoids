"""FastAPI application exposing endpoints for the Minecraft plugin."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
import uvicorn

from .manager import WithdrawalManager, WithdrawalNotFoundError
from .models import WithdrawalRequest, WithdrawalStatus


class WithdrawalCreate(BaseModel):
    player_name: str = Field(..., description="Minecraft username initiating the withdrawal")
    wallet_address: str = Field(..., description="Destination crypto wallet address")
    amount: Decimal = Field(..., gt=Decimal("0"))
    currency: str = Field(..., description="Currency ticker, e.g. BTC")
    player_uuid: Optional[str] = Field(None, description="Minecraft UUID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional context from the plugin")


class WithdrawalResponse(BaseModel):
    id: int
    status: str
    player_name: str
    wallet_address: str
    amount: str
    currency: str
    player_uuid: Optional[str]
    metadata: Dict[str, Any]
    transaction_id: Optional[str]
    failure_reason: Optional[str]

    @classmethod
    def from_request(cls, request: WithdrawalRequest) -> "WithdrawalResponse":
        return cls(**request.to_api_dict())


class WithdrawalListResponse(BaseModel):
    withdrawals: List[WithdrawalResponse]


def create_app(manager: WithdrawalManager) -> FastAPI:
    app = FastAPI(title="Withdrawal Bridge", version="0.1.0")

    def get_manager() -> WithdrawalManager:
        return manager

    @app.get("/health", status_code=status.HTTP_200_OK)
    async def healthcheck() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/withdrawals",
        response_model=WithdrawalResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create a withdrawal request",
    )
    async def create_withdrawal(payload: WithdrawalCreate, mgr: WithdrawalManager = Depends(get_manager)) -> WithdrawalResponse:
        request = await mgr.create_request(
            player_name=payload.player_name,
            wallet_address=payload.wallet_address,
            amount=payload.amount,
            currency=payload.currency,
            player_uuid=payload.player_uuid,
            metadata=payload.metadata,
        )
        return WithdrawalResponse.from_request(request)

    @app.get("/withdrawals/{request_id}", response_model=WithdrawalResponse)
    async def get_withdrawal(request_id: int, mgr: WithdrawalManager = Depends(get_manager)) -> WithdrawalResponse:
        try:
            request = await mgr.get_request(request_id)
        except WithdrawalNotFoundError as exc:  # pragma: no cover - simple propagation
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return WithdrawalResponse.from_request(request)

    @app.get("/withdrawals", response_model=WithdrawalListResponse)
    async def list_withdrawals(
        status_filter: Optional[str] = Query(None, alias="status"),
        limit: int = Query(50, ge=1, le=200),
        mgr: WithdrawalManager = Depends(get_manager),
    ) -> WithdrawalListResponse:
        status_value: Optional[WithdrawalStatus]
        if status_filter is None:
            status_value = None
        else:
            try:
                status_value = WithdrawalStatus(status_filter.lower())
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid status filter") from exc
        requests = await mgr.store.list_requests(status=status_value, limit=limit)  # type: ignore[attr-defined]
        return WithdrawalListResponse(withdrawals=[WithdrawalResponse.from_request(req) for req in requests])

    return app


class WithdrawalServer:
    """Helper that runs the FastAPI application using Uvicorn."""

    def __init__(self, app: FastAPI, *, host: str, port: int) -> None:
        self._config = uvicorn.Config(app, host=host, port=port, loop="asyncio", lifespan="on")
        self._server = uvicorn.Server(self._config)

    async def serve(self) -> None:
        await self._server.serve()

    async def shutdown(self) -> None:
        self._server.should_exit = True


__all__ = ["create_app", "WithdrawalServer"]
