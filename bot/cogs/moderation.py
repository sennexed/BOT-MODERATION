from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EnterpriseModBot, case_id


def is_mod(interaction: discord.Interaction) -> bool:
    if not interaction.user or not isinstance(interaction.user, discord.Member):
        return False
    return interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator


class AICog(commands.Cog):
    def __init__(self, bot: EnterpriseModBot) -> None:
        self.bot = bot

    ai_group = app_commands.Group(name="ai", description="AI moderation settings")
    risk_group = app_commands.Group(name="risk", description="Risk management commands")

    @ai_group.command(name="sensitivity", description="Set AI sensitivity (0-1)")
    @app_commands.check(is_mod)
    async def ai_sensitivity(self, interaction: discord.Interaction, value: app_commands.Range[float, 0.0, 1.0]) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, ai_sensitivity=float(value))
        embed = discord.Embed(title="AI Sensitivity Updated", color=discord.Color.green())
        embed.description = f"Sensitivity set to `{value:.2f}`"
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="confidence-threshold", description="Set AI confidence threshold (0-1)")
    @app_commands.check(is_mod)
    async def confidence_threshold(self, interaction: discord.Interaction, value: app_commands.Range[float, 0.0, 1.0]) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, confidence_threshold=float(value))
        embed = discord.Embed(title="AI Confidence Threshold Updated", color=discord.Color.green())
        embed.description = f"Threshold set to `{value:.2f}`"
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="strict-mode", description="Toggle strict AI mode")
    @app_commands.check(is_mod)
    async def strict_mode(self, interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, ai_strict_mode=enabled, strict_ai_enabled=enabled)
        embed = discord.Embed(title="Strict Mode", color=discord.Color.orange())
        embed.description = f"Strict mode {'enabled' if enabled else 'disabled'}."
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="shadow-mode", description="Toggle shadow mode")
    @app_commands.check(is_mod)
    async def shadow_mode(self, interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, ai_shadow_mode=enabled)
        embed = discord.Embed(title="Shadow Mode", color=discord.Color.blurple())
        embed.description = f"Shadow mode {'enabled' if enabled else 'disabled'}"
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="explain", description="Explain AI decision for a case")
    @app_commands.check(is_mod)
    async def explain(self, interaction: discord.Interaction, case_id_value: str) -> None:
        assert interaction.guild
        case = await self.bot.db.get_case(interaction.guild.id, case_id_value)
        if not case:
            await interaction.response.send_message(embed=discord.Embed(title="Case Not Found", color=discord.Color.red()), ephemeral=True)
            return
        embed = discord.Embed(title=f"AI Explanation: {case_id_value}", color=discord.Color.dark_teal())
        embed.add_field(name="Category", value=str(case["category"]), inline=True)
        embed.add_field(name="Severity", value=str(case["severity"]), inline=True)
        embed.add_field(name="Confidence", value=f"{float(case['ai_confidence'] or 0.0):.2f}", inline=True)
        embed.description = str(case["explanation"])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @risk_group.command(name="user", description="View risk score for a user")
    @app_commands.check(is_mod)
    async def risk_user(self, interaction: discord.Interaction, user: discord.Member) -> None:
        assert interaction.guild
        row = await self.bot.db.get_risk_row(interaction.guild.id, user.id)
        risk = float(row["risk_score"]) if row else 0.0
        embed = discord.Embed(title="User Risk Profile", color=discord.Color.gold())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Risk Score", value=f"{risk:.1f}/100")
        await interaction.response.send_message(embed=embed)

    @risk_group.command(name="leaderboard", description="Top users by risk")
    @app_commands.check(is_mod)
    async def risk_leaderboard(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        rows = await self.bot.db.risk_leaderboard(interaction.guild.id, limit=10)
        embed = discord.Embed(title="Risk Leaderboard", color=discord.Color.red())
        if not rows:
            embed.description = "No risk data yet."
        else:
            lines = [f"`#{idx}` <@{int(r['user_id'])}> - `{float(r['risk_score']):.1f}`" for idx, r in enumerate(rows, start=1)]
            embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @risk_group.command(name="reset", description="Reset risk score")
    @app_commands.check(is_mod)
    async def risk_reset(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        assert interaction.guild
        await self.bot.db.reset_risk(interaction.guild.id, user.id if user else None)
        embed = discord.Embed(title="Risk Reset", color=discord.Color.green())
        embed.description = f"Risk reset for {user.mention if user else 'all users'}"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="raidmode", description="Set raid defense mode")
    @app_commands.check(is_mod)
    @app_commands.choices(mode=[
        app_commands.Choice(name="auto", value="auto"),
        app_commands.Choice(name="strict", value="strict"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def raidmode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, raid_mode=mode.value)
        embed = discord.Embed(title="Raid Mode Updated", color=discord.Color.dark_orange())
        embed.description = f"Raid mode set to `{mode.value}`"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="moderate", description="Manual moderation action")
    @app_commands.check(is_mod)
    @app_commands.choices(action=[
        app_commands.Choice(name="verbal", value="verbal"),
        app_commands.Choice(name="temp", value="temp"),
        app_commands.Choice(name="permanent", value="permanent"),
        app_commands.Choice(name="timeout", value="timeout"),
    ])
    async def moderate(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        action: app_commands.Choice[str],
        reason: str,
    ) -> None:
        assert interaction.guild
        moderator = interaction.user
        assert isinstance(moderator, discord.Member)

        me = interaction.guild.me
        if not me or user.top_role >= me.top_role:
            await interaction.response.send_message(embed=discord.Embed(title="Role Hierarchy Block", description="Cannot moderate this user.", color=discord.Color.red()), ephemeral=True)
            return

        cid = case_id()
        expires_at = None
        if action.value == "temp":
            cfg = await self.bot.db.get_or_create_guild_config(interaction.guild.id)
            expires_at = self.bot.db.now() + timedelta(days=int(cfg["escalation_temp_days"]))

        await self.bot.db.create_infraction(
            case_id=cid,
            guild_id=interaction.guild.id,
            user_id=user.id,
            moderator_id=moderator.id,
            source="manual",
            category="manual",
            severity="medium",
            action=action.value,
            risk_score=0,
            ai_confidence=None,
            reason=reason,
            explanation=reason,
            expires_at=expires_at,
        )

        await self.bot.db.log_moderator_action(interaction.guild.id, moderator.id, action.value, cid, {"target": user.id, "reason": reason})

        if action.value == "timeout" and me.guild_permissions.moderate_members:
            await user.timeout(discord.utils.utcnow() + timedelta(hours=48), reason=reason)

        embed = discord.Embed(title="Manual Moderation Applied", color=discord.Color.dark_red())
        embed.add_field(name="Case", value=cid)
        embed.add_field(name="Action", value=action.value)
        embed.add_field(name="User", value=user.mention)
        embed.description = reason
        await interaction.response.send_message(embed=embed)


async def setup(bot: EnterpriseModBot) -> None:
    await bot.add_cog(AICog(bot))
