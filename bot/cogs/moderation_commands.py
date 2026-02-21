from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class ModerationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _require_guild(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="warnings", description="Show warning summary for a user")
    @app_commands.describe(user="User to inspect")
    async def warnings(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not await self._require_guild(interaction):
            return

        counts = await self.bot.db.get_warning_counts(interaction.guild.id, user.id)
        embed = discord.Embed(title=f"Warnings for {user}")
        embed.add_field(name="Verbal", value=str(counts["verbal"]), inline=True)
        embed.add_field(name="Active Temp", value=str(counts["temp"]), inline=True)
        embed.add_field(name="Permanent", value=str(counts["permanent"]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="showwarnings", description="Show recent warning history for a user")
    @app_commands.describe(user="User to inspect")
    async def showwarnings(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not await self._require_guild(interaction):
            return

        rows = await self.bot.db.get_recent_warnings(interaction.guild.id, user.id, limit=15)
        if not rows:
            await interaction.response.send_message("No warnings found.", ephemeral=True)
            return

        lines = []
        for row in rows:
            created = row["created_at"].strftime("%Y-%m-%d %H:%M UTC")
            entry = f"{created} | {row['warning_type']} | {row['severity']} | {row['reason'][:80]}"
            if row["expires_at"]:
                exp = row["expires_at"].strftime("%Y-%m-%d")
                entry += f" | expires {exp}"
            lines.append(entry)

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="risk", description="Show current user risk score")
    @app_commands.describe(user="User to inspect")
    async def risk(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not await self._require_guild(interaction):
            return

        risk_score = await self.bot.cache.get_risk_score(
            interaction.guild.id,
            user.id,
            self.bot.settings.risk_decay_per_hour,
        )
        await interaction.response.send_message(
            f"Risk score for {user.mention}: `{risk_score:.2f}`",
            ephemeral=True,
        )

    @app_commands.command(name="modstats", description="Show server moderation statistics")
    async def modstats(self, interaction: discord.Interaction) -> None:
        if not await self._require_guild(interaction):
            return

        stats = await self.bot.db.get_mod_stats(interaction.guild.id)
        top_users = "\n".join([f"<@{uid}>: {count}" for uid, count in stats["top_users"]]) or "No data"

        embed = discord.Embed(title="Moderation Stats")
        embed.add_field(name="Total Warnings", value=str(stats["total"]), inline=True)
        embed.add_field(name="Last 24h", value=str(stats["last_24h"]), inline=True)
        embed.add_field(name="Verbal", value=str(stats["verbal"]), inline=True)
        embed.add_field(name="Temp", value=str(stats["temp"]), inline=True)
        embed.add_field(name="Permanent", value=str(stats["permanent"]), inline=True)
        embed.add_field(name="Top Users", value=top_users, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="appeal", description="Create an appeal record")
    @app_commands.describe(user="User appealing", note="Appeal note")
    async def appeal(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        note: app_commands.Range[str, 5, 400],
    ) -> None:
        if not await self._require_guild(interaction):
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return

        if interaction.user.id != user.id and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "You can only submit appeals for yourself unless you are a moderator.",
                ephemeral=True,
            )
            return

        await self.bot.db.create_appeal(
            guild_id=interaction.guild.id,
            user_id=user.id,
            requested_by=interaction.user.id,
            note=note,
        )
        await interaction.response.send_message("Appeal submitted for moderator review.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCommands(bot))
