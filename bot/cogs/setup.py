from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EnterpriseModBot

COLOR_GREEN = discord.Color.from_rgb(46, 204, 113)
COLOR_YELLOW = discord.Color.from_rgb(241, 196, 15)
COLOR_RED = discord.Color.from_rgb(231, 76, 60)
COLOR_BLUE = discord.Color.from_rgb(52, 152, 219)
COLOR_GREY = discord.Color.from_rgb(149, 165, 166)
COLOR_ORANGE = discord.Color.from_rgb(230, 126, 34)

THREAT_LABELS = {
    0: "🟢 Normal",
    1: "🟡 Suspicious",
    2: "🟠 Active",
    3: "🔴 Severe",
    4: "🚨 Critical",
}

THREAT_MODES = {
    0: "adaptive",
    1: "watch",
    2: "hardened",
    3: "lockdown",
    4: "emergency",
}


class SetupRepository:
    def __init__(self, bot: EnterpriseModBot) -> None:
        self.bot = bot

    async def ensure_columns(self) -> None:
        async with self.bot.db.pool.acquire() as conn:
            await conn.execute(
                """
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS max_warnings_before_escalation INTEGER NOT NULL DEFAULT 5;
                """
            )
            await conn.execute(
                """
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS auto_reinforcement BOOLEAN NOT NULL DEFAULT TRUE;
                """
            )
            await conn.execute(
                """
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS threat_level INTEGER NOT NULL DEFAULT 0;
                """
            )
            await conn.execute(
                """
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS auto_lockdown BOOLEAN NOT NULL DEFAULT FALSE;
                """
            )
            await conn.execute(
                """
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS reinforcement_mode TEXT NOT NULL DEFAULT 'adaptive';
                """
            )
            await conn.execute(
                """
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS reinforcement_last_escalation TIMESTAMPTZ;
                """
            )
            await conn.execute(
                """
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS reinforcement_manual_override BOOLEAN NOT NULL DEFAULT FALSE;
                """
            )

    async def get_config(self, guild_id: int) -> dict[str, Any]:
        async with self.bot.db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO guild_config (guild_id)
                VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                guild_id,
            )
            row = await conn.fetchrow(
                """
                SELECT
                    guild_id,
                    ai_sensitivity,
                    confidence_threshold,
                    ai_strict_mode,
                    ai_shadow_mode,
                    raid_mode,
                    escalation_temp_days,
                    log_channel_id,
                    mod_role_id,
                    admin_role_id,
                    analytics_enabled,
                    strict_ai_enabled,
                    max_warnings_before_escalation,
                    auto_reinforcement,
                    threat_level,
                    auto_lockdown,
                    reinforcement_mode,
                    reinforcement_last_escalation,
                    reinforcement_manual_override,
                    updated_at
                FROM guild_config
                WHERE guild_id = $1
                """,
                guild_id,
            )
        return dict(row) if row else {}

    async def update_config(self, guild_id: int, updates: dict[str, Any]) -> None:
        if not updates:
            return

        allowed = {
            "ai_sensitivity",
            "confidence_threshold",
            "ai_strict_mode",
            "strict_ai_enabled",
            "raid_mode",
            "max_warnings_before_escalation",
            "auto_reinforcement",
            "threat_level",
            "auto_lockdown",
            "reinforcement_mode",
            "reinforcement_last_escalation",
            "reinforcement_manual_override",
            "log_channel_id",
            "mod_role_id",
        }

        keys = [k for k in updates if k in allowed]
        if not keys:
            return

        assignments = [f"{key} = ${idx}" for idx, key in enumerate(keys, start=2)]
        values = [updates[key] for key in keys]
        query = (
            "UPDATE guild_config "
            f"SET {', '.join(assignments)}, updated_at = NOW() "
            "WHERE guild_id = $1"
        )

        async with self.bot.db.pool.acquire() as conn:
            await conn.execute(query, guild_id, *values)

    async def reset_defaults(self, guild_id: int) -> None:
        await self.update_config(
            guild_id,
            {
                "ai_sensitivity": 0.5,
                "confidence_threshold": 0.6,
                "ai_strict_mode": False,
                "strict_ai_enabled": False,
                "raid_mode": "auto",
                "max_warnings_before_escalation": 5,
                "auto_reinforcement": True,
                "threat_level": 0,
                "auto_lockdown": False,
                "reinforcement_mode": "adaptive",
                "reinforcement_last_escalation": None,
                "reinforcement_manual_override": False,
            },
        )

    async def get_analytics(self, guild_id: int) -> dict[str, int]:
        async with self.bot.db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)::INT AS total,
                    COUNT(*) FILTER (WHERE action = 'verbal')::INT AS verbal,
                    COUNT(*) FILTER (WHERE action = 'temp')::INT AS temporary,
                    COUNT(*) FILTER (WHERE action = 'permanent')::INT AS permanent,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours')::INT AS last_24h,
                    COUNT(*) FILTER (
                        WHERE created_at >= NOW() - INTERVAL '48 hours'
                        AND created_at < NOW() - INTERVAL '24 hours'
                    )::INT AS prev_24h
                FROM infractions
                WHERE guild_id = $1
                """,
                guild_id,
            )
        if not row:
            return {
                "total": 0,
                "verbal": 0,
                "temporary": 0,
                "permanent": 0,
                "last_24h": 0,
                "prev_24h": 0,
            }
        return {
            "total": int(row["total"] or 0),
            "verbal": int(row["verbal"] or 0),
            "temporary": int(row["temporary"] or 0),
            "permanent": int(row["permanent"] or 0),
            "last_24h": int(row["last_24h"] or 0),
            "prev_24h": int(row["prev_24h"] or 0),
        }


def _is_admin(member: discord.abc.User | discord.Member | None) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def _fmt_bool(value: bool, on_text: str = "Enabled", off_text: str = "Disabled") -> str:
    return f"🟢 {on_text}" if value else f"⚪ {off_text}"


def _fmt_raid_mode(mode: str) -> str:
    mode = mode.lower()
    if mode == "strict":
        return "🔴 Strict"
    if mode == "auto":
        return "🟡 Auto"
    return "⚪ Off"


def _fmt_trend(last_24h: int, prev_24h: int) -> str:
    if last_24h > prev_24h:
        return "🔴 Rising"
    if last_24h < prev_24h:
        return "🟢 Improving"
    return "⚪ Stable"


def _fmt_last_escalation(value: Any) -> str:
    if value is None:
        return "⚪ None"
    if isinstance(value, datetime):
        return discord.utils.format_dt(value, style="R")
    return "⚪ None"


class PanelButton(discord.ui.Button["ControlCenterView"]):
    def __init__(self, label: str, emoji: str, panel: str, row: int, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.switch_panel(interaction, self.panel)


class BackToDashboardButton(discord.ui.Button["ControlCenterView"]):
    def __init__(self) -> None:
        super().__init__(label="Back to Dashboard", emoji="⬅", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.switch_panel(interaction, "dashboard")


class AISensitivitySelect(discord.ui.Select["ControlCenterView"]):
    def __init__(self, current: float) -> None:
        options = [
            discord.SelectOption(label="Low (0.4)", value="0.4", default=abs(current - 0.4) < 1e-9),
            discord.SelectOption(label="Balanced (0.5)", value="0.5", default=abs(current - 0.5) < 1e-9),
            discord.SelectOption(label="High (0.7)", value="0.7", default=abs(current - 0.7) < 1e-9),
            discord.SelectOption(label="Strict (0.85)", value="0.85", default=abs(current - 0.85) < 1e-9),
        ]
        super().__init__(placeholder="Select AI sensitivity", options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            value = float(self.values[0])
            await self.view.apply_update(interaction, {"ai_sensitivity": value}, f"Sensitivity updated to `{value:.2f}`")


class ConfidenceSelect(discord.ui.Select["ControlCenterView"]):
    def __init__(self, current: float) -> None:
        options = [
            discord.SelectOption(label="Confidence 0.5", value="0.5", default=abs(current - 0.5) < 1e-9),
            discord.SelectOption(label="Confidence 0.6", value="0.6", default=abs(current - 0.6) < 1e-9),
            discord.SelectOption(label="Confidence 0.7", value="0.7", default=abs(current - 0.7) < 1e-9),
            discord.SelectOption(label="Confidence 0.8", value="0.8", default=abs(current - 0.8) < 1e-9),
        ]
        super().__init__(placeholder="Select confidence threshold", options=options, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            value = float(self.values[0])
            await self.view.apply_update(interaction, {"confidence_threshold": value}, f"Confidence threshold set to `{value:.2f}`")


class RaidModeSelect(discord.ui.Select["ControlCenterView"]):
    def __init__(self, current: str) -> None:
        normalized = current.lower()
        options = [
            discord.SelectOption(label="Off", value="off", default=normalized == "off"),
            discord.SelectOption(label="Auto", value="auto", default=normalized == "auto"),
            discord.SelectOption(label="Strict", value="strict", default=normalized == "strict"),
        ]
        super().__init__(placeholder="Select raid mode", options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            mode = self.values[0]
            await self.view.apply_update(interaction, {"raid_mode": mode}, f"Raid mode switched to `{mode}`")


class WarningThresholdSelect(discord.ui.Select["ControlCenterView"]):
    def __init__(self, current: int) -> None:
        options = [
            discord.SelectOption(label="3", value="3", default=current == 3),
            discord.SelectOption(label="5", value="5", default=current == 5),
            discord.SelectOption(label="7", value="7", default=current == 7),
        ]
        super().__init__(placeholder="Max warnings before escalation", options=options, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            warnings = int(self.values[0])
            await self.view.apply_update(
                interaction,
                {"max_warnings_before_escalation": warnings},
                f"Escalation threshold set to `{warnings}` warnings",
            )


class LogChannelSelect(discord.ui.ChannelSelect["ControlCenterView"]):
    def __init__(self, current_channel_id: int | None) -> None:
        super().__init__(
            placeholder="Select logging channel",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
            ],
            min_values=1,
            max_values=1,
            row=1,
        )
        self.current_channel_id = current_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None:
            return

        channel = self.values[0]

        # In discord.py 2.4+, announcement channels are TextChannel
        if not isinstance(channel, discord.TextChannel):
            await self.view.set_notice_and_render(
                interaction,
                "Invalid channel type selected",
                ok=False,
            )
            return

        await self.view.apply_update(
            interaction,
            {"log_channel_id": channel.id},
            f"Logging channel updated to {channel.mention}",
        )

class ModRoleSelect(discord.ui.RoleSelect["ControlCenterView"]):
    def __init__(self, current_role_id: int | None) -> None:
        super().__init__(placeholder="Select moderator role", min_values=1, max_values=1, row=1)
        self.current_role_id = current_role_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None:
            return
        role = self.values[0]
        await self.view.apply_update(interaction, {"mod_role_id": role.id}, f"Moderator role set to {role.mention}")


class ControlCenterView(discord.ui.View):
    def __init__(self, bot: EnterpriseModBot, guild_id: int, actor_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.actor_id = actor_id
        self.repo = SetupRepository(bot)
        self.panel = "dashboard"
        self.notice = ""
        self.notice_ok = True
        self.config: dict[str, Any] = {}
        self.analytics: dict[str, int] = {
            "total": 0,
            "verbal": 0,
            "temporary": 0,
            "permanent": 0,
            "last_24h": 0,
            "prev_24h": 0,
        }
        self.message: discord.InteractionMessage | None = None

    async def initialize(self) -> None:
        await self.repo.ensure_columns()
        await self.refresh_state()
        self.rebuild_components()

    async def refresh_state(self) -> None:
        self.config = await self.repo.get_config(self.guild_id)
        self.analytics = await self.repo.get_analytics(self.guild_id)

    def _escalation_status(self) -> str:
        threat = max(0, min(4, int(self.config.get("threat_level", 0) or 0)))
        manual_override = bool(self.config.get("reinforcement_manual_override", False))
        auto_reinforcement = bool(self.config.get("auto_reinforcement", True))
        if manual_override:
            return "🟣 Manual override active"
        if not auto_reinforcement:
            return "⚪ Auto escalation paused"
        if threat >= 4:
            return "🚨 Emergency escalation"
        if threat >= 3:
            return "🔴 Lockdown escalation"
        if threat >= 2:
            return "🟠 Hardened escalation"
        if threat >= 1:
            return "🟡 Watch escalation"
        return "🟢 Baseline posture"

    def _threat_updates(self, target_level: int) -> tuple[dict[str, Any], str]:
        threat = max(0, min(4, int(target_level)))
        updates: dict[str, Any] = {
            "threat_level": threat,
            "reinforcement_last_escalation": datetime.now(UTC),
        }

        manual_override = bool(self.config.get("reinforcement_manual_override", False))
        auto_reinforcement = bool(self.config.get("auto_reinforcement", True))
        auto_lockdown = bool(self.config.get("auto_lockdown", False))

        if not manual_override and auto_reinforcement:
            mode = THREAT_MODES.get(threat, "adaptive")
            updates["reinforcement_mode"] = mode
            if auto_lockdown and threat >= 3:
                updates["raid_mode"] = "strict"
            elif threat <= 1:
                updates["raid_mode"] = "auto"

        notice = f"Threat level set to `{threat}`"
        if manual_override:
            notice += " (manual override)"
        return updates, notice

    def _status_color_for_dashboard(self) -> discord.Color:
        threat = int(self.config.get("threat_level", 0) or 0)
        if threat >= 4:
            return COLOR_RED
        if threat >= 2:
            return COLOR_YELLOW
        return COLOR_BLUE

    def _ai_status(self) -> str:
        strict = bool(self.config.get("strict_ai_enabled", False))
        return "🔴 Strict" if strict else "🟢 Balanced"

    def _reinforcement_level(self) -> str:
        threat = max(0, min(4, int(self.config.get("threat_level", 0) or 0)))
        return THREAT_LABELS[threat]

    def _log_channel_mention(self) -> str:
        channel_id = self.config.get("log_channel_id")
        if channel_id:
            return f"<#{int(channel_id)}>"
        return "⚪ Not configured"

    def _mod_role_mention(self) -> str:
        role_id = self.config.get("mod_role_id")
        if role_id:
            return f"<@&{int(role_id)}>"
        return "⚪ Not configured"

    def build_embed(self) -> discord.Embed:
        if self.panel == "dashboard":
            embed = discord.Embed(
                title="UOI Moderator • Control Center",
                description=(
                    "Centralized configuration hub for AI moderation, security posture, reinforcement controls, "
                    "analytics, and compliance routing."
                ),
                color=self._status_color_for_dashboard(),
            )
            embed.add_field(name="🤖 AI Status", value=self._ai_status(), inline=True)
            embed.add_field(name="🛡 Security Mode", value=_fmt_raid_mode(str(self.config.get("raid_mode", "auto"))), inline=True)
            embed.add_field(name="🚨 Reinforcement Level", value=self._reinforcement_level(), inline=True)
            embed.add_field(
                name="🔒 Auto Lockdown",
                value=_fmt_bool(bool(self.config.get("auto_lockdown", False)), "Enabled", "Disabled"),
                inline=True,
            )
            embed.add_field(name="📈 Total Infractions", value=f"`{self.analytics['total']}`", inline=True)
            embed.add_field(name="🕒 Last 24h Activity", value=f"`{self.analytics['last_24h']}`", inline=True)
        elif self.panel == "ai":
            strict = bool(self.config.get("strict_ai_enabled", False))
            embed = discord.Embed(
                title="🤖 AI Configuration",
                description="Fine-tune model sensitivity and confidence gating for production moderation behavior.",
                color=COLOR_BLUE if not strict else COLOR_RED,
            )
            embed.add_field(name="Sensitivity", value=f"`{float(self.config.get('ai_sensitivity', 0.5)):.2f}`", inline=True)
            embed.add_field(name="Confidence Threshold", value=f"`{float(self.config.get('confidence_threshold', 0.6)):.2f}`", inline=True)
            embed.add_field(name="Strict AI", value=_fmt_bool(strict, "On", "Off"), inline=True)
        elif self.panel == "security":
            embed = discord.Embed(
                title="🛡 Security Controls",
                description="Manage raid detection posture, escalation thresholds, and reinforcement automation.",
                color=COLOR_YELLOW,
            )
            embed.add_field(name="Raid Mode", value=_fmt_raid_mode(str(self.config.get("raid_mode", "auto"))), inline=True)
            embed.add_field(
                name="Max Warnings",
                value=f"`{int(self.config.get('max_warnings_before_escalation', 5) or 5)}`",
                inline=True,
            )
            embed.add_field(
                name="Auto Reinforcement",
                value=_fmt_bool(bool(self.config.get("auto_reinforcement", True)), "Enabled", "Disabled"),
                inline=True,
            )
        elif self.panel == "reinforcement":
            threat = max(0, min(4, int(self.config.get("threat_level", 0) or 0)))
            embed = discord.Embed(
                title="🚨 Reinforcement Engine",
                description="Control active threat posture and lockdown behavior with real-time overrides.",
                color=COLOR_RED if threat >= 3 else COLOR_ORANGE if threat >= 2 else COLOR_GREEN,
            )
            embed.add_field(name="Threat Level", value=THREAT_LABELS[threat], inline=True)
            embed.add_field(
                name="Auto Lockdown",
                value=_fmt_bool(bool(self.config.get("auto_lockdown", False)), "Enabled", "Disabled"),
                inline=True,
            )
            embed.add_field(name="Reinforcement Mode", value=f"`{str(self.config.get('reinforcement_mode', 'adaptive')).title()}`", inline=True)
            embed.add_field(name="Escalation", value=self._escalation_status(), inline=False)
            embed.add_field(name="Last Escalation", value=_fmt_last_escalation(self.config.get("reinforcement_last_escalation")), inline=False)
        elif self.panel == "analytics":
            last_24h = self.analytics["last_24h"]
            prev_24h = self.analytics["prev_24h"]
            embed = discord.Embed(
                title="📊 Analytics",
                description="Moderation activity snapshot across total outcomes and 24-hour movement.",
                color=COLOR_BLUE,
            )
            embed.add_field(name="Total Infractions", value=f"`{self.analytics['total']}`", inline=True)
            embed.add_field(name="Verbal", value=f"`{self.analytics['verbal']}`", inline=True)
            embed.add_field(name="Temporary", value=f"`{self.analytics['temporary']}`", inline=True)
            embed.add_field(name="Permanent", value=f"`{self.analytics['permanent']}`", inline=True)
            embed.add_field(name="Last 24h", value=f"`{last_24h}`", inline=True)
            embed.add_field(name="Trend", value=_fmt_trend(last_24h, prev_24h), inline=True)
        elif self.panel == "logging":
            embed = discord.Embed(
                title="📁 Logging",
                description="Route moderation and reinforcement events into a dedicated auditing channel.",
                color=COLOR_GREY,
            )
            embed.add_field(name="Log Channel", value=self._log_channel_mention(), inline=False)
            embed.add_field(name="Status", value="🟢 Ready" if self.config.get("log_channel_id") else "🟡 Configuration required", inline=True)
        elif self.panel == "roles":
            embed = discord.Embed(
                title="👥 Roles",
                description="Set moderator access role for panel operations and governance controls.",
                color=COLOR_BLUE,
            )
            embed.add_field(name="Current Mod Role", value=self._mod_role_mention(), inline=False)
        else:
            embed = discord.Embed(title="UOI Moderator • Control Center", color=COLOR_BLUE)

        embed.add_field(name="────────────", value="Use controls below to update settings instantly.", inline=False)
        if self.notice:
            status = "✅" if self.notice_ok else "❌"
            embed.set_footer(text=f"{status} {self.notice}")
        else:
            embed.set_footer(text="Session timeout: 5 minutes")
        return embed

    def rebuild_components(self) -> None:
        self.clear_items()
        if self.panel == "dashboard":
            self.add_item(PanelButton(label="AI", emoji="🤖", panel="ai", row=0, style=discord.ButtonStyle.primary))
            self.add_item(PanelButton(label="Security", emoji="🛡", panel="security", row=0, style=discord.ButtonStyle.secondary))
            self.add_item(PanelButton(label="Reinforcement", emoji="🚨", panel="reinforcement", row=0, style=discord.ButtonStyle.danger))
            self.add_item(PanelButton(label="Analytics", emoji="📊", panel="analytics", row=1, style=discord.ButtonStyle.secondary))
            self.add_item(PanelButton(label="Logging", emoji="📁", panel="logging", row=1, style=discord.ButtonStyle.secondary))
            self.add_item(PanelButton(label="Roles", emoji="👥", panel="roles", row=1, style=discord.ButtonStyle.secondary))
            self.add_item(RefreshButton())
            self.add_item(ResetDefaultsButton())
            return

        if self.panel == "ai":
            self.add_item(AISensitivitySelect(float(self.config.get("ai_sensitivity", 0.5) or 0.5)))
            self.add_item(ConfidenceSelect(float(self.config.get("confidence_threshold", 0.6) or 0.6)))
            self.add_item(ToggleStrictAIButton())
            self.add_item(BackToDashboardButton())
            return

        if self.panel == "security":
            self.add_item(RaidModeSelect(str(self.config.get("raid_mode", "auto"))))
            self.add_item(WarningThresholdSelect(int(self.config.get("max_warnings_before_escalation", 5) or 5)))
            self.add_item(ToggleAutoReinforcementButton())
            self.add_item(BackToDashboardButton())
            return

        if self.panel == "reinforcement":
            self.add_item(IncreaseThreatButton())
            self.add_item(DecreaseThreatButton())
            self.add_item(ResetThreatButton())
            self.add_item(ToggleAutoLockdownButton())
            self.add_item(ManualOverrideButton())
            self.add_item(BackToDashboardButton())
            return

        if self.panel == "analytics":
            self.add_item(PanelRefreshButton())
            self.add_item(BackToDashboardButton())
            return

        if self.panel == "logging":
            self.add_item(LogChannelSelect(self.config.get("log_channel_id")))
            self.add_item(TestLogButton())
            self.add_item(BackToDashboardButton())
            return

        if self.panel == "roles":
            self.add_item(ModRoleSelect(self.config.get("mod_role_id")))
            self.add_item(BackToDashboardButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            if not interaction.response.is_done():
                await interaction.response.send_message("This panel is no longer valid for this server.", ephemeral=True)
            return False
        if interaction.user.id != self.actor_id or not _is_admin(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message("Administrator access is required to use this control panel.", ephemeral=True)
            return False
        return True

    async def switch_panel(self, interaction: discord.Interaction, panel: str) -> None:
        try:
            self.panel = panel
            self.notice = ""
            await self.refresh_state()
            self.rebuild_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except Exception:
            await self.set_notice_and_render(interaction, "Failed to switch panel", ok=False)

    async def apply_update(self, interaction: discord.Interaction, updates: dict[str, Any], notice: str) -> None:
        try:
            await self.repo.update_config(self.guild_id, updates)
            self.notice = notice
            self.notice_ok = True
            await self.refresh_state()
            self.rebuild_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except Exception:
            await self.set_notice_and_render(interaction, "Database update failed", ok=False)

    async def set_notice_and_render(self, interaction: discord.Interaction, notice: str, ok: bool) -> None:
        self.notice = notice
        self.notice_ok = ok
        await self.refresh_state()
        self.rebuild_components()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=self.build_embed(), view=self)
        else:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                return


class RefreshButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            self.view.notice = "Dashboard refreshed"
            self.view.notice_ok = True
            await self.view.refresh_state()
            self.view.rebuild_components()
            await interaction.response.edit_message(embed=self.view.build_embed(), view=self.view)


class ResetDefaultsButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Reset Defaults", emoji="🧹", style=discord.ButtonStyle.danger, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            try:
                await self.view.repo.reset_defaults(self.view.guild_id)
                self.view.notice = "Defaults restored"
                self.view.notice_ok = True
            except Exception:
                self.view.notice = "Failed to reset defaults"
                self.view.notice_ok = False
            await self.view.refresh_state()
            self.view.rebuild_components()
            await interaction.response.edit_message(embed=self.view.build_embed(), view=self.view)


class ToggleStrictAIButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Toggle Strict AI", style=discord.ButtonStyle.primary, row=3)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            enabled = not bool(self.view.config.get("strict_ai_enabled", False))
            await self.view.apply_update(
                interaction,
                {"strict_ai_enabled": enabled, "ai_strict_mode": enabled},
                f"Strict AI {'enabled' if enabled else 'disabled'}",
            )


class ToggleAutoReinforcementButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Toggle Auto Reinforcement", style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            enabled = not bool(self.view.config.get("auto_reinforcement", True))
            await self.view.apply_update(
                interaction,
                {"auto_reinforcement": enabled},
                f"Auto reinforcement {'enabled' if enabled else 'disabled'}",
            )


class IncreaseThreatButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Increase Threat", style=discord.ButtonStyle.danger, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            current = int(self.view.config.get("threat_level", 0) or 0)
            updates, notice = self.view._threat_updates(min(4, current + 1))
            await self.view.apply_update(interaction, updates, notice)


class DecreaseThreatButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Decrease Threat", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            current = int(self.view.config.get("threat_level", 0) or 0)
            updates, notice = self.view._threat_updates(max(0, current - 1))
            await self.view.apply_update(interaction, updates, notice)


class ResetThreatButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Reset Threat", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            updates, notice = self.view._threat_updates(0)
            await self.view.apply_update(interaction, updates, notice)


class ToggleAutoLockdownButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Toggle Auto Lockdown", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            enabled = not bool(self.view.config.get("auto_lockdown", False))
            await self.view.apply_update(
                interaction,
                {"auto_lockdown": enabled},
                f"Auto lockdown {'enabled' if enabled else 'disabled'}",
            )


class ManualOverrideButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Manual Override", style=discord.ButtonStyle.primary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            override = not bool(self.view.config.get("reinforcement_manual_override", False))
            mode = "manual" if override else "adaptive"
            await self.view.apply_update(
                interaction,
                {"reinforcement_manual_override": override, "reinforcement_mode": mode},
                f"Manual override {'enabled' if override else 'disabled'}",
            )


class PanelRefreshButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            await self.view.set_notice_and_render(interaction, "Analytics refreshed", ok=True)


class TestLogButton(discord.ui.Button[ControlCenterView]):
    def __init__(self) -> None:
        super().__init__(label="Test Log", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None or interaction.guild is None:
            return

        channel_id = self.view.config.get("log_channel_id")
        if not channel_id:
            await self.view.set_notice_and_render(interaction, "No log channel configured", ok=False)
            return

        channel = interaction.guild.get_channel(int(channel_id))
        if channel is None or not isinstance(channel, discord.TextChannel):
            await self.view.set_notice_and_render(interaction, "Configured log channel is unavailable", ok=False)
            return

        embed = discord.Embed(
            title="UOI Moderator • Log Test",
            description="Logging pipeline check completed successfully.",
            color=COLOR_BLUE,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Source", value="Control Center", inline=True)
        embed.add_field(name="Status", value="🟢 Operational", inline=True)
        try:
            await channel.send(embed=embed)
            await self.view.set_notice_and_render(interaction, f"Test log sent to {channel.mention}", ok=True)
        except discord.HTTPException:
            await self.view.set_notice_and_render(interaction, "Failed to send test log", ok=False)


class SetupCog(commands.Cog):
    def __init__(self, bot: EnterpriseModBot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Open the UOI Moderator control center")
    async def setup_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not _is_admin(interaction.user):
            await interaction.response.send_message("Administrator permission is required.", ephemeral=True)
            return

        view = ControlCenterView(self.bot, interaction.guild.id, interaction.user.id)
        try:
            await view.initialize()
            await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
            view.message = await interaction.original_response()
        except Exception:
            if interaction.response.is_done():
                await interaction.edit_original_response(content="Failed to open control center.", embed=None, view=None)
            else:
                await interaction.response.send_message("Failed to open control center.", ephemeral=True)


async def setup(bot: EnterpriseModBot) -> None:
    await bot.add_cog(SetupCog(bot))
