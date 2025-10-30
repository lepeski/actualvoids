"""Entry point for running the withdrawal bot and API server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import Iterable

from .config import Settings
from .discord_bot import WithdrawalBot
from .manager import WithdrawalManager
from .server import WithdrawalServer, create_app
from .storage import WithdrawalStore
from .wallet import DummyWalletClient, HTTPWalletClient, PiteasWalletClient


async def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    store = WithdrawalStore(settings.database_path)
    if settings.wallet_provider == "piteas":
        wallet = PiteasWalletClient(
            base_url=settings.piteas_api_url or "https://api.piteas.io",
            api_key=settings.piteas_api_key,
            project_id=settings.piteas_project_id,
            wallet_id=settings.piteas_wallet_id,
            asset_symbol=settings.piteas_asset_symbol,
            network=settings.piteas_network,
            priority=settings.piteas_priority,
        )
    elif settings.wallet_endpoint:
        wallet = HTTPWalletClient(
            settings.wallet_endpoint,
            api_key=settings.wallet_api_key,
        )
    else:
        wallet = DummyWalletClient()
    manager = WithdrawalManager(store=store, wallet=wallet)
    app = create_app(manager)
    server = WithdrawalServer(app, host=settings.api_host, port=settings.api_port)
    bot = WithdrawalBot(settings=settings, manager=manager)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    for sig in _supported_signals():  # pragma: no cover - depends on platform
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            signal.signal(sig, lambda *_: stop_event.set())

    server_task = asyncio.create_task(server.serve(), name="withdrawal-api")
    server_task.add_done_callback(lambda _: stop_event.set())

    async def _run_bot() -> None:
        try:
            await bot.start(settings.discord_token)
        finally:
            await bot.close()

    bot_task = asyncio.create_task(_run_bot(), name="discord-bot")
    bot_task.add_done_callback(lambda _: stop_event.set())

    await stop_event.wait()

    bot_task.cancel()
    await server.shutdown()
    server_task.cancel()

    with contextlib.suppress(asyncio.CancelledError):
        await bot_task
    with contextlib.suppress(asyncio.CancelledError):
        await server_task

    await store.cleanup()


def _supported_signals() -> Iterable[int]:
    yield signal.SIGINT
    yield signal.SIGTERM


if __name__ == "__main__":
    asyncio.run(main())
