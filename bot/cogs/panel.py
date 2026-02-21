from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EnterpriseModBot, case_id


class ActionSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Warning type",
            options=[
                discord.SelectOption(label="verbal", value="verbal"),
                discord.SelectOption(label="temp", value="temp"),
                discord.SelectOption(label="permanent", value="permanent"),
            ],
        )


class DurationSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Duration",
            options=[
                discord.SelectOption(label="24h", value="24"),
                discord.SelectOption(label="7d", value=str(24 * 7)),
                discord.SelectOption(label="30d", value=str(24 * 30)),
            ],
        )


class SeveritySelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Severity level",
            options=[
                discord.SelectOption(label="low", value="low"),
                discord.SelectOption(label="medium", value="medium"),
                discord.SelectOption(label="high", value="high"),
                discord.SelectOption(label="extreme", value="extreme"),
            ],
        )


class ModerationPanel(discord.ui.View):
    def __init__(self, bot: EnterpriseModBot, target: discord.Member, moderator_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.target = target
        self.moderator_id = moderator_id
        self.warning_type = "verbal"
        self.duration_hours = 24
        self.severity = "medium"

        self.warning_select = ActionSelect()
        self.duration_select = DurationSelect()
        self.severity_select = SeveritySelect()
        self.warning_select.callback = self._warning_callback
        self.duration_select.callback = self._duration_callback
        self.severity_select.callback = self._severity_callback
        self.add_item(self.warning_select)
        self.add_item(self.duration_select)
        self.add_item(self.severity_select)

    async def _warning_callback(self, interaction: discord.Interaction) -> None:
        self.warning_type = self.warning_select.values[0]
        await interaction.response.send_message(embed=discord.Embed(title="Panel Updated", description=f"Warning type: `{self.warning_type}`", color=discord.Color.blurple()), ephemeral=True)

    async def _duration_callback(self, interaction: discord.Interaction) -> None:
        self.duration_hours = int(self.duration_select.values[0])
        await interaction.response.send_message(embed=discord.Embed(title="Panel Updated", description=f"Duration: `{self.duration_hours}` hours", color=discord.Color.blurple()), ephemeral=True)

    async def _severity_callback(self, interaction: discord.Interaction) -> None:
        self.severity = self.severity_select.values[0]
        await interaction.response.send_message(embed=discord.Embed(title="Panel Updated", description=f"Severity: `{self.severity}`", color=discord.Color.blurple()), ephemeral=True)

    async def _create_case(self, interaction: discord.Interaction, action: str, reason: str) -> str:
        assert interaction.guild
        cid = case_id()
        expiry = None
        if action == "temp":
            expiry = self.bot.db.now() + timedelta(hours=self.duration_hours)
        await self.bot.db.create_infraction(
            case_id=cid,
            guild_id=interaction.guild.id,
            user_id=self.target.id,
            moderator_id=self.moderator_id,
            source="panel",
            category="manual",
            severity=self.severity,
            action=action,
            risk_score=0,
            ai_confidence=None,
            reason=reason,
            explanation=reason,
            expires_at=expiry,
        )
        return cid

    @discord.ui.button(label="View Infractions", style=discord.ButtonStyle.secondary)
    async def view_infractions(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        assert interaction.guild
        counts = await self.bot.db.get_user_infraction_counts(interaction.guild.id, self.target.id)
        embed = discord.Embed(title="Infraction Snapshot", color=discord.Color.orange())
        embed.add_field(name="User", value=self.target.mention)
        embed.add_field(name="Verbal", value=str(counts["verbal"]))
        embed.add_field(name="Temp", value=str(counts["temp"]))
        embed.add_field(name="Permanent", value=str(counts["permanent"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Escalate", style=discord.ButtonStyle.danger)
    async def escalate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cid = await self._create_case(interaction, self.warning_type, "Panel escalation")
        await interaction.response.send_message(embed=discord.Embed(title="Escalation Applied", description=f"Case `{cid}` created with action `{self.warning_type}`", color=discord.Color.red()), ephemeral=True)

    @discord.ui.button(label="Override AI", style=discord.ButtonStyle.primary)
    async def override_ai(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        assert interaction.guild
        await self.bot.db.log_moderator_action(interaction.guild.id, self.moderator_id, "override_ai", None, {"target": self.target.id, "severity": self.severity})
        await interaction.response.send_message(embed=discord.Embed(title="AI Override Logged", color=discord.Color.blurple()), ephemeral=True)

    @discord.ui.button(label="Timeout User", style=discord.ButtonStyle.secondary)
    async def timeout_user(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        assert interaction.guild
        me = interaction.guild.me
        if not me or self.target.top_role >= me.top_role or not me.guild_permissions.moderate_members:
            await interaction.response.send_message(embed=discord.Embed(title="Timeout Blocked", color=discord.Color.red()), ephemeral=True)
            return
        until = discord.utils.utcnow() + timedelta(hours=self.duration_hours)
        await self.target.timeout(until, reason="Panel timeout")
        cid = await self._create_case(interaction, "timeout", "Panel timeout")
        await interaction.response.send_message(embed=discord.Embed(title="Timeout Applied", description=f"Case `{cid}`", color=discord.Color.orange()), ephemeral=True)

    @discord.ui.button(label="Lock Channel", style=discord.ButtonStyle.danger)
    async def lock_channel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        assert interaction.guild and isinstance(interaction.channel, discord.TextChannel)
        channel = interaction.channel
        me = interaction.guild.me
        if not me or not channel.permissions_for(me).manage_channels:
            await interaction.response.send_message(embed=discord.Embed(title="Lock Failed", description="Missing permissions.", color=discord.Color.red()), ephemeral=True)
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason="Panel channel lock")
        await interaction.response.send_message(embed=discord.Embed(title="Channel Locked", description=channel.mention, color=discord.Color.dark_red()), ephemeral=True)

    @discord.ui.button(label="Enable Raid Mode", style=discord.ButtonStyle.primary)
    async def enable_raid_mode(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, raid_mode="strict")
        await interaction.response.send_message(embed=discord.Embed(title="Raid Mode Enabled", description="Mode set to strict.", color=discord.Color.dark_orange()), ephemeral=True)

    @discord.ui.button(label="Toggle Strict Mode", style=discord.ButtonStyle.secondary)
    async def toggle_strict(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        assert interaction.guild
        cfg = await self.bot.db.get_or_create_guild_config(interaction.guild.id)
        enabled = not bool(cfg["ai_strict_mode"])
        await self.bot.db.update_guild_config(interaction.guild.id, ai_strict_mode=enabled, strict_ai_enabled=enabled)
        await interaction.response.send_message(embed=discord.Embed(title="Strict Mode Toggled", description=f"Enabled: `{enabled}`", color=discord.Color.gold()), ephemeral=True)

    @discord.ui.button(label="Reset Risk", style=discord.ButtonStyle.success)
    async def reset_risk(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        assert interaction.guild
        await self.bot.db.reset_risk(interaction.guild.id, self.target.id)
        await interaction.response.send_message(embed=discord.Embed(title="Risk Reset", description=self.target.mention, color=discord.Color.green()), ephemeral=True)


class PanelCog(commands.Cog):
    def __init__(self, bot: EnterpriseModBot) -> None:
        self.bot = bot

    @app_commands.command(name="moderation-panel", description="Open interactive moderation panel")
    async def moderation_panel(self, interaction: discord.Interaction, user: discord.Member) -> None:
        assert isinstance(interaction.user, discord.Member)
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(embed=discord.Embed(title="Permission Denied", color=discord.Color.red()), ephemeral=True)
            return
        embed = discord.Embed(title="Moderation Panel", color=discord.Color.dark_teal())
        embed.description = f"Target: {user.mention}\nAdjust dropdowns and use action buttons."
        await interaction.response.send_message(embed=embed, view=ModerationPanel(self.bot, user, interaction.user.id), ephemeral=True)


async def setup(bot: EnterpriseModBot) -> None:
    await bot.add_cog(PanelCog(bot))
