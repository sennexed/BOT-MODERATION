from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class AdminCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _require_mod(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Manage Messages permission required.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="clearwarnings", description="Clear active temporary warnings for a user")
    @app_commands.describe(user="User to clear temp warnings from")
    async def clearwarnings(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not await self._require_mod(interaction):
            return

        removed = await self.bot.db.clear_temp_warnings(interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"Cleared {removed} active temporary warnings for {user.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="resetwarnings", description="Reset all warnings for a user")
    @app_commands.describe(user="User to reset warning history for")
    async def resetwarnings(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not await self._require_mod(interaction):
            return

        removed = await self.bot.db.reset_all_warnings(interaction.guild.id, user.id)
        await self.bot.cache.clear_risk_score(interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"Reset warning history ({removed} records) and cleared risk for {user.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="config", description="Configure moderation settings")
    @app_commands.describe(sensitivity="Confidence threshold 0.00-1.00")
    async def config(self, interaction: discord.Interaction, sensitivity: app_commands.Range[float, 0.0, 1.0]) -> None:
        if not await self._require_mod(interaction):
            return

        await self.bot.cache.set_sensitivity(interaction.guild.id, sensitivity)
        await interaction.response.send_message(
            f"Updated confidence sensitivity to `{sensitivity:.2f}`.",
            ephemeral=True,
        )

    @app_commands.command(name="lockdown", description="Enable or disable lockdown mode")
    @app_commands.describe(mode="Enable or disable")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="enable", value="enable"),
            app_commands.Choice(name="disable", value="disable"),
        ]
    )
    async def lockdown(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        if not await self._require_mod(interaction):
            return

        enabled = mode.value == "enable"
        await self.bot.cache.set_lockdown(interaction.guild.id, enabled)
        await interaction.response.send_message(
            f"Lockdown mode {'enabled' if enabled else 'disabled'}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCommands(bot))
