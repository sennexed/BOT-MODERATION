from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EnterpriseModBot


class SetupView(discord.ui.View):
    def __init__(self, bot: EnterpriseModBot, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="AI", style=discord.ButtonStyle.primary)
    async def ai_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.db.update_guild_config(self.guild_id, ai_sensitivity=0.65, confidence_threshold=0.68)
        await interaction.response.send_message(embed=discord.Embed(title="AI Setup Applied", description="Sensitivity and confidence tuned for balanced moderation.", color=discord.Color.green()), ephemeral=True)

    @discord.ui.button(label="Security", style=discord.ButtonStyle.secondary)
    async def security_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.db.update_guild_config(self.guild_id, raid_mode="auto", strict_ai_enabled=True)
        await interaction.response.send_message(embed=discord.Embed(title="Security Setup Applied", description="Raid mode auto and strict AI enabled.", color=discord.Color.orange()), ephemeral=True)

    @discord.ui.button(label="Escalation", style=discord.ButtonStyle.danger)
    async def escalation_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.db.update_guild_config(self.guild_id, escalation_temp_days=30)
        await interaction.response.send_message(embed=discord.Embed(title="Escalation Setup Applied", description="Temp duration set to 30 days.", color=discord.Color.red()), ephemeral=True)

    @discord.ui.button(label="Analytics", style=discord.ButtonStyle.success)
    async def analytics_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.bot.db.update_guild_config(self.guild_id, analytics_enabled=True)
        await interaction.response.send_message(embed=discord.Embed(title="Analytics Enabled", color=discord.Color.blurple()), ephemeral=True)


class SetupCog(commands.Cog):
    def __init__(self, bot: EnterpriseModBot) -> None:
        self.bot = bot

    setup_group = app_commands.Group(name="setup", description="Enterprise moderation setup")

    @setup_group.command(name="quick", description="Open interactive setup wizard")
    async def quick(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        await self.bot.db.get_or_create_guild_config(interaction.guild.id)
        embed = discord.Embed(title="Setup Wizard", description="Use buttons to apply enterprise presets.", color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, view=SetupView(self.bot, interaction.guild.id), ephemeral=True)

    @setup_group.command(name="ai", description="Configure AI settings")
    @app_commands.describe(sensitivity="0..1", threshold="0..1")
    async def ai(self, interaction: discord.Interaction, sensitivity: app_commands.Range[float, 0.0, 1.0], threshold: app_commands.Range[float, 0.0, 1.0]) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, ai_sensitivity=float(sensitivity), confidence_threshold=float(threshold))
        embed = discord.Embed(title="AI Config Updated", color=discord.Color.green())
        embed.description = f"Sensitivity `{sensitivity:.2f}`, threshold `{threshold:.2f}`"
        await interaction.response.send_message(embed=embed)

    @setup_group.command(name="security", description="Configure security mode")
    @app_commands.choices(raid_mode=[
        app_commands.Choice(name="auto", value="auto"),
        app_commands.Choice(name="strict", value="strict"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def security(self, interaction: discord.Interaction, raid_mode: app_commands.Choice[str]) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, raid_mode=raid_mode.value)
        embed = discord.Embed(title="Security Updated", description=f"Raid mode: `{raid_mode.value}`", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)

    @setup_group.command(name="escalation", description="Configure escalation policy")
    async def escalation(self, interaction: discord.Interaction, temp_days: app_commands.Range[int, 1, 90]) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, escalation_temp_days=int(temp_days))
        await interaction.response.send_message(embed=discord.Embed(title="Escalation Updated", description=f"Temp duration: `{temp_days}` days", color=discord.Color.red()))

    @setup_group.command(name="logs", description="Set moderation log channel")
    async def logs(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, log_channel_id=channel.id)
        await interaction.response.send_message(embed=discord.Embed(title="Log Channel Set", description=channel.mention, color=discord.Color.dark_blue()))

    @setup_group.command(name="roles", description="Set moderation/admin roles")
    async def roles(self, interaction: discord.Interaction, mod_role: discord.Role, admin_role: discord.Role) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, mod_role_id=mod_role.id, admin_role_id=admin_role.id)
        embed = discord.Embed(title="Role Config Updated", color=discord.Color.dark_green())
        embed.add_field(name="Moderator Role", value=mod_role.mention)
        embed.add_field(name="Admin Role", value=admin_role.mention)
        await interaction.response.send_message(embed=embed)

    @setup_group.command(name="analytics", description="Enable/disable analytics")
    async def analytics(self, interaction: discord.Interaction, enabled: bool) -> None:
        assert interaction.guild
        await self.bot.db.update_guild_config(interaction.guild.id, analytics_enabled=enabled)
        await interaction.response.send_message(embed=discord.Embed(title="Analytics Updated", description=f"Enabled: `{enabled}`", color=discord.Color.gold()))

    @setup_group.command(name="status", description="Show setup status")
    async def status(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        cfg = await self.bot.db.get_or_create_guild_config(interaction.guild.id)
        embed = discord.Embed(title="Setup Status", color=discord.Color.blurple())
        embed.add_field(name="AI Sensitivity", value=f"{float(cfg['ai_sensitivity']):.2f}")
        embed.add_field(name="Confidence Threshold", value=f"{float(cfg['confidence_threshold']):.2f}")
        embed.add_field(name="Raid Mode", value=str(cfg["raid_mode"]))
        embed.add_field(name="Strict AI", value=str(bool(cfg["strict_ai_enabled"])))
        embed.add_field(name="Shadow Mode", value=str(bool(cfg["ai_shadow_mode"])))
        embed.add_field(name="Analytics", value=str(bool(cfg["analytics_enabled"])))
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: EnterpriseModBot) -> None:
    await bot.add_cog(SetupCog(bot))
