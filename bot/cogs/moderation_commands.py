from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class ModerationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="modstats", description="Show moderation statistics for this server")
    async def modstats(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Guild only command.", ephemeral=True)
            return

        stats = await self.bot.db.get_mod_stats(interaction.guild.id)
        embed = discord.Embed(title="Moderation Stats")
        embed.add_field(name="Total Messages Logged", value=str(stats["total"]), inline=False)
        embed.add_field(name="Violations", value=str(stats["violations"]), inline=True)
        embed.add_field(name="Last 24h", value=str(stats["last_24h"]), inline=True)
        by_severity = "\n".join(f"{k}: {v}" for k, v in stats["by_severity"].items()) or "No data"
        embed.add_field(name="By Severity", value=by_severity, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="viewinfractions", description="View recent infractions for a user")
    @app_commands.describe(user="Member to inspect")
    async def viewinfractions(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Guild only command.", ephemeral=True)
            return

        rows = await self.bot.db.get_user_infractions(interaction.guild.id, user.id)
        if not rows:
            await interaction.response.send_message(f"No infractions found for {user.mention}", ephemeral=True)
            return

        lines = [
            f"{row['created_at'].strftime('%Y-%m-%d %H:%M UTC')} | {row['severity']} | {row['action_taken']} | {row['reasoning'][:80]}"
            for row in rows
        ]
        content = "\n".join(lines[:12])
        await interaction.response.send_message(f"Recent infractions for {user.mention}:\n{content}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCommands(bot))
