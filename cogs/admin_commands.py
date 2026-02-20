from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class AdminCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _check_permissions(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Guild only command.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Manage Server permission required.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="clearrisk", description="Reset a member risk score")
    @app_commands.describe(user="Member to reset")
    async def clearrisk(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not await self._check_permissions(interaction):
            return
        await self.bot.reinforcement.clear_risk(interaction.guild.id, user.id)
        await interaction.response.send_message(f"Risk score cleared for {user.mention}", ephemeral=True)

    @app_commands.command(name="lockdown", description="Enable or disable anti-raid lockdown mode")
    @app_commands.describe(mode="enable or disable")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="enable", value="enable"),
            app_commands.Choice(name="disable", value="disable"),
        ]
    )
    async def lockdown(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        if not await self._check_permissions(interaction):
            return

        enabled = mode.value == "enable"
        await self.bot.anti_spam.set_lockdown_enabled(interaction.guild.id, enabled)
        await self.bot.db.log_lockdown_event(
            interaction.guild.id,
            interaction.channel_id,
            enabled,
            f"Manual anti-raid mode set to {mode.value}",
        )
        await interaction.response.send_message(
            f"Anti-raid lockdown mode {'enabled' if enabled else 'disabled'}.",
            ephemeral=True,
        )

    @app_commands.command(name="setthreshold", description="Set anti-raid threshold and window")
    @app_commands.describe(
        toxic_messages="Toxic message count threshold",
        seconds="Window in seconds",
    )
    async def setthreshold(
        self,
        interaction: discord.Interaction,
        toxic_messages: app_commands.Range[int, 2, 50],
        seconds: app_commands.Range[int, 5, 120],
    ) -> None:
        if not await self._check_permissions(interaction):
            return

        await self.bot.anti_spam.set_raid_threshold(interaction.guild.id, toxic_messages, seconds)
        await interaction.response.send_message(
            f"Raid threshold updated: {toxic_messages} toxic messages in {seconds}s.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCommands(bot))
