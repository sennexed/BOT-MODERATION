from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EnterpriseModBot


def is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator


class AdminCog(commands.Cog):
    def __init__(self, bot: EnterpriseModBot) -> None:
        self.bot = bot

    @app_commands.command(name="server-health", description="Server moderation health snapshot")
    @app_commands.check(is_admin)
    async def server_health(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        stats = await self.bot.analytics.snapshot(interaction.guild.id)
        embed = discord.Embed(title="Server Health", color=discord.Color.green())
        embed.add_field(name="Total Infractions", value=str(stats["total"]))
        embed.add_field(name="24h Activity", value=str(stats["last_24h"]))
        embed.add_field(name="Avg AI Confidence", value=f"{stats['avg_ai_confidence']:.2f}")
        embed.add_field(name="False Positives", value=str(stats["false_positives"]))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="toxicity-trend", description="Hourly toxicity trend")
    @app_commands.check(is_admin)
    async def toxicity_trend(self, interaction: discord.Interaction, hours: app_commands.Range[int, 6, 168] = 24) -> None:
        assert interaction.guild
        trend = await self.bot.analytics.toxicity_trend(interaction.guild.id, hours)
        embed = discord.Embed(title="Toxicity Trend", color=discord.Color.orange())
        if not trend:
            embed.description = "No data for selected range."
        else:
            embed.description = "\n".join(f"`{b}` -> `{c}`" for b, c in trend[-18:])
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ai-performance", description="AI performance and false positive indicators")
    @app_commands.check(is_admin)
    async def ai_performance(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        stats = await self.bot.analytics.snapshot(interaction.guild.id)
        total = max(stats["total"], 1)
        false_positive_rate = (stats["false_positives"] / total) * 100
        embed = discord.Embed(title="AI Performance", color=discord.Color.blurple())
        embed.add_field(name="Average Confidence", value=f"{stats['avg_ai_confidence']:.2f}")
        embed.add_field(name="Overrides", value=str(stats["false_positives"]))
        embed.add_field(name="Estimated False Positive %", value=f"{false_positive_rate:.2f}%")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mod-activity", description="Top moderator activity")
    @app_commands.check(is_admin)
    async def mod_activity(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        stats = await self.bot.analytics.snapshot(interaction.guild.id)
        embed = discord.Embed(title="Moderator Activity", color=discord.Color.dark_blue())
        if not stats["mod_actions"]:
            embed.description = "No moderator actions logged yet."
        else:
            embed.description = "\n".join(f"<@{uid}>: `{count}` actions" for uid, count in stats["mod_actions"])
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="risk-leaderboard", description="Global risk leaderboard for this server")
    @app_commands.check(is_admin)
    async def risk_leaderboard(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        rows = await self.bot.db.risk_leaderboard(interaction.guild.id)
        embed = discord.Embed(title="Risk Leaderboard", color=discord.Color.red())
        if not rows:
            embed.description = "No risk data available."
        else:
            embed.description = "\n".join(f"`#{i}` <@{int(r['user_id'])}> - `{float(r['risk_score']):.1f}`" for i, r in enumerate(rows, start=1))
        await interaction.response.send_message(embed=embed)


async def setup(bot: EnterpriseModBot) -> None:
    await bot.add_cog(AdminCog(bot))
