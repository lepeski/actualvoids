"""Discord bot implementation for crypto withdrawals."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Settings
from .manager import WithdrawalManager, WithdrawalNotFoundError, WithdrawalStateError
from .models import WithdrawalRequest, WithdrawalStatus
from .wallet import WalletError

_LOGGER = logging.getLogger(__name__)


def build_request_embed(request: WithdrawalRequest) -> discord.Embed:
    """Render an embed describing a withdrawal request."""

    colors = {
        WithdrawalStatus.PENDING: discord.Color.yellow(),
        WithdrawalStatus.PROCESSING: discord.Color.blurple(),
        WithdrawalStatus.APPROVED: discord.Color.green(),
        WithdrawalStatus.REJECTED: discord.Color.red(),
        WithdrawalStatus.FAILED: discord.Color.dark_red(),
    }

    embed = discord.Embed(
        title=f"Withdrawal Request #{request.id}",
        color=colors.get(request.status, discord.Color.light_grey()),
    )
    embed.add_field(name="Player", value=request.player_name, inline=True)
    embed.add_field(name="Amount", value=f"{request.amount} {request.currency}", inline=True)
    embed.add_field(name="Wallet", value=request.wallet_address, inline=False)
    if request.player_uuid:
        embed.add_field(name="Player UUID", value=request.player_uuid, inline=False)
    if request.metadata:
        formatted = "\n".join(f"**{key}**: {value}" for key, value in request.metadata.items())
        embed.add_field(name="Metadata", value=formatted, inline=False)
    embed.add_field(name="Status", value=request.status.value.title(), inline=True)
    embed.add_field(name="Created", value=discord.utils.format_dt(request.created_at, style="R"), inline=True)
    embed.add_field(name="Updated", value=discord.utils.format_dt(request.updated_at, style="R"), inline=True)
    if request.approved_by:
        embed.add_field(name="Handled By", value=request.approved_by, inline=True)
    if request.transaction_id:
        embed.add_field(name="Transaction", value=request.transaction_id, inline=False)
    if request.failure_reason:
        embed.add_field(name="Reason", value=request.failure_reason, inline=False)
    return embed


class WithdrawalRequestView(discord.ui.View):
    """Interactive controls for pending withdrawals."""

    def __init__(
        self,
        *,
        manager: WithdrawalManager,
        settings: Settings,
        request_id: int,
    ) -> None:
        super().__init__(timeout=None)
        self.manager = manager
        self.settings = settings
        self.request_id = request_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None:
            return False
        if self._is_authorised(interaction.user):
            return True
        await interaction.response.send_message(
            "You are not authorized to manage withdrawals.", ephemeral=True
        )
        return False

    def _is_authorised(self, user: discord.abc.User) -> bool:
        if isinstance(user, discord.Member):
            if user.guild_permissions.administrator:
                return True
            allowed_roles = set(self.settings.admin_role_ids)
            if not allowed_roles:
                return True
            return any(role.id in allowed_roles for role in getattr(user, "roles", []))
        return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        assert interaction.user is not None
        self._disable_buttons()
        try:
            request = await self.manager.approve_request(
                self.request_id,
                admin_name=str(interaction.user),
                admin_id=getattr(interaction.user, "id", 0),
            )
        except WithdrawalStateError as exc:
            self._enable_buttons()
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except WalletError as exc:
            self._enable_buttons()
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = build_request_embed(request)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        assert interaction.user is not None
        self._disable_buttons()
        try:
            request = await self.manager.reject_request(
                self.request_id,
                admin_name=str(interaction.user),
                admin_id=getattr(interaction.user, "id", 0),
                reason="Rejected by administrator",
            )
        except WithdrawalStateError as exc:
            self._enable_buttons()
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = build_request_embed(request)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    def _disable_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    def _enable_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = False


class WithdrawalBot(commands.Bot):
    """Discord bot that coordinates withdrawal approvals."""

    def __init__(self, settings: Settings, manager: WithdrawalManager) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = False
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)
        self.settings = settings
        self.manager = manager
        self.manager.add_listener(self._handle_new_request)

        @self.tree.command(name="withdrawal_status", description="Check the status of a withdrawal request.")
        async def _withdrawal_status(interaction: discord.Interaction, request_id: int) -> None:
            try:
                request = await self.manager.get_request(request_id)
            except WithdrawalNotFoundError:
                await interaction.response.send_message(
                    f"Withdrawal request {request_id} was not found.", ephemeral=True
                )
                return
            embed = build_request_embed(request)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def setup_hook(self) -> None:
        await self._restore_pending_views()
        await self._sync_commands()

    async def on_ready(self) -> None:  # pragma: no cover - runtime logging
        _LOGGER.info("Bot connected as %s (id=%s)", self.user, getattr(self.user, "id", "?"))

    async def _sync_commands(self) -> None:
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def _restore_pending_views(self) -> None:
        pending = await self.manager.list_pending(limit=100)
        for request in pending:
            if request.discord_message_id is None:
                continue
            self.add_view(
                WithdrawalRequestView(manager=self.manager, settings=self.settings, request_id=request.id),
                message_id=request.discord_message_id,
            )

    async def _handle_new_request(self, request: WithdrawalRequest) -> None:
        channel = self.get_channel(self.settings.withdrawal_channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(self.settings.withdrawal_channel_id)
            except discord.HTTPException:
                _LOGGER.error("Unable to locate withdrawal channel %s", self.settings.withdrawal_channel_id)
                return
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            _LOGGER.error("Configured withdrawal channel is not a text-compatible channel")
            return
        embed = build_request_embed(request)
        view = WithdrawalRequestView(manager=self.manager, settings=self.settings, request_id=request.id)
        message = await channel.send(embed=embed, view=view)
        await self.manager.attach_message(request.id, message.id)


__all__ = ["WithdrawalBot", "WithdrawalRequestView", "build_request_embed"]
