from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable, Coroutine

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

SENSITIVITY_LEVELS: dict[str, float] = {
    "low": 0.35,
    "medium": 0.55,
    "high": 0.75,
    "aggressive": 0.9,
}


def sensitivity_to_label(value: float) -> str:
    if value < 0.45:
        return "Low"
    if value < 0.65:
        return "Medium"
    if value < 0.85:
        return "High"
    return "Aggressive"


def escalation_stage_description(temp_count: int, permanent_count: int) -> str:
    if permanent_count >= 5:
        return "Critical: auto-timeout threshold reached (5 permanent)."
    if permanent_count >= 3:
        return "High: nearing auto-timeout threshold."
    if temp_count >= 3:
        return "Elevated: repeated temp infractions detected."
    return "Normal: no immediate escalation pressure."


class UserIdModal(discord.ui.Modal):
    def __init__(self, title: str, callback: Callable[[discord.Interaction, int], Coroutine[None, None, None]]) -> None:
        super().__init__(title=title)
        self._callback = callback

        self.user_id = discord.ui.TextInput(
            label="User ID",
            placeholder="Enter target user ID",
            min_length=17,
            max_length=20,
            required=True,
        )
        self.add_item(self.user_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            user_id = int(str(self.user_id.value).strip())
        except ValueError:
            await interaction.response.send_message("Invalid user ID.", ephemeral=True)
            return

        await self._callback(interaction, user_id)


class AddWarningModal(discord.ui.Modal):
    def __init__(self, view: "ModerationPanelView") -> None:
        super().__init__(title="Add Warning")
        self.view = view

        self.user_id = discord.ui.TextInput(label="User ID", min_length=17, max_length=20, required=True)
        self.warning_type = discord.ui.TextInput(
            label="Warning Type",
            placeholder="verbal | temp | permanent",
            default="temp",
            min_length=4,
            max_length=10,
            required=True,
        )
        self.severity = discord.ui.TextInput(
            label="Severity",
            placeholder="LOW | MEDIUM | HIGH | SEVERE",
            default="MEDIUM",
            min_length=3,
            max_length=10,
            required=True,
        )
        self.reason = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            min_length=4,
            max_length=300,
            required=True,
        )
        self.confidence = discord.ui.TextInput(
            label="Confidence (0.00-1.00)",
            default="0.75",
            min_length=1,
            max_length=4,
            required=True,
        )

        self.add_item(self.user_id)
        self.add_item(self.warning_type)
        self.add_item(self.severity)
        self.add_item(self.reason)
        self.add_item(self.confidence)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("Guild-only action.", ephemeral=True)
                return

            user_id = int(str(self.user_id.value).strip())
            warning_type = str(self.warning_type.value).strip().lower()
            if warning_type not in {"verbal", "temp", "permanent"}:
                await interaction.response.send_message("Warning type must be verbal, temp, or permanent.", ephemeral=True)
                return

            severity = str(self.severity.value).strip().upper()
            confidence = float(str(self.confidence.value).strip())
            if not 0.0 <= confidence <= 1.0:
                await interaction.response.send_message("Confidence must be between 0.00 and 1.00.", ephemeral=True)
                return

            expires_at = None
            if warning_type == "temp":
                expires_at = self.view.bot.db.utcnow() + timedelta(days=self.view.bot.settings.temp_warning_days)

            await interaction.response.defer(ephemeral=True)
            await self.view.bot.db.add_infraction(
                guild_id=guild.id,
                user_id=user_id,
                warning_type=warning_type,
                severity=severity,
                reason=str(self.reason.value).strip(),
                confidence=confidence,
                expires_at=expires_at,
            )

            if warning_type == "temp":
                await self.view.bot.db.promote_temp_to_permanent_if_needed(guild.id, user_id)

            risk_delta = {"verbal": 0.5, "temp": 2.0, "permanent": 4.0}[warning_type]
            await self.view.bot.cache.increment_risk_score(
                guild.id,
                user_id,
                risk_delta,
                self.view.bot.settings.risk_decay_per_hour,
            )

            await self.view.show_warnings_panel(interaction)
            await interaction.followup.send(f"Warning added for `<@{user_id}>` as `{warning_type}`.", ephemeral=True)
        except Exception as exc:
            await self.view.send_error(interaction, exc)


class ConfidenceThresholdModal(discord.ui.Modal):
    def __init__(self, view: "ModerationPanelView") -> None:
        super().__init__(title="Set Confidence Threshold")
        self.view = view
        self.threshold = discord.ui.TextInput(
            label="Threshold (0.00-1.00)",
            default=f"{self.view.current_sensitivity:.2f}",
            min_length=1,
            max_length=4,
            required=True,
        )
        self.add_item(self.threshold)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("Guild-only action.", ephemeral=True)
                return

            value = float(str(self.threshold.value).strip())
            if not 0.0 <= value <= 1.0:
                await interaction.response.send_message("Threshold must be between 0.00 and 1.00.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            await self.view.bot.cache.set_sensitivity(guild.id, value)
            self.view.current_sensitivity = value
            await self.view.show_ai_panel(interaction)
            await interaction.followup.send(f"Confidence threshold set to `{value:.2f}`.", ephemeral=True)
        except Exception as exc:
            await self.view.send_error(interaction, exc)


class InspectUserModal(discord.ui.Modal):
    def __init__(self, view: "ModerationPanelView") -> None:
        super().__init__(title="Inspect User")
        self.view = view
        self.user_id = discord.ui.TextInput(label="User ID", min_length=17, max_length=20, required=True)
        self.add_item(self.user_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("Guild-only action.", ephemeral=True)
                return

            user_id = int(str(self.user_id.value).strip())
            await interaction.response.defer(ephemeral=True)
            self.view.inspected_user_id = user_id
            await self.view.show_user_inspector_panel(interaction)
        except Exception as exc:
            await self.view.send_error(interaction, exc)


class SensitivitySelect(discord.ui.Select):
    def __init__(self, view: "ModerationPanelView") -> None:
        self.panel_view = view
        options = [
            discord.SelectOption(label="Low", value="low", description="Lower strictness"),
            discord.SelectOption(label="Medium", value="medium", description="Balanced strictness"),
            discord.SelectOption(label="High", value="high", description="Strict"),
            discord.SelectOption(label="Aggressive", value="aggressive", description="Most strict"),
        ]
        super().__init__(
            placeholder=f"Sensitivity: {sensitivity_to_label(view.current_sensitivity)}",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("Guild-only action.", ephemeral=True)
                return

            level = self.values[0]
            value = SENSITIVITY_LEVELS[level]
            await interaction.response.defer(ephemeral=True)
            await self.panel_view.bot.cache.set_sensitivity(guild.id, value)
            self.panel_view.current_sensitivity = value
            await self.panel_view.show_ai_panel(interaction)
            await interaction.followup.send(f"Sensitivity set to `{level.title()}` ({value:.2f}).", ephemeral=True)
        except Exception as exc:
            await self.panel_view.send_error(interaction, exc)


class ModerationPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, timeout: float = 240.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self.panel_message: discord.InteractionMessage | None = None
        self.current_panel = "main"
        self.current_sensitivity = bot.settings.default_sensitivity
        self.inspected_user_id: int | None = None
        self._timed_out = False

    async def initialize(self) -> discord.Embed:
        self.current_sensitivity = await self.bot.cache.get_sensitivity(self.guild_id, self.bot.settings.default_sensitivity)
        await self._rebuild_components()
        return await self._build_main_embed()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._timed_out:
            if interaction.response.is_done():
                await interaction.followup.send("Panel expired. Run `/panel` again.", ephemeral=True)
            else:
                await interaction.response.send_message("Panel expired. Run `/panel` again.", ephemeral=True)
            return False

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Guild-only interaction.", ephemeral=True)
            return False

        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Manage Messages permission required.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        self._timed_out = True
        for item in self.children:
            item.disabled = True

        if self.panel_message is None:
            return

        try:
            embed = await self._current_embed()
            embed.set_footer(text="Panel timed out due to inactivity. Use /panel to reopen.")
            await self.panel_message.edit(embed=embed, view=self)
        except Exception:
            logger.exception("Failed to disable panel on timeout")

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[discord.ui.View]) -> None:
        await self.send_error(interaction, error)

    async def send_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("Panel callback failed", exc_info=error)
        message = "Action failed. Check bot permissions and try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("Unable to send error response")

    async def _run_action(self, interaction: discord.Interaction, action: Callable[[], Coroutine[None, None, None]]) -> None:
        try:
            await action()
        except Exception as exc:
            await self.send_error(interaction, exc)

    async def _edit_panel(self) -> None:
        if self.panel_message is None:
            return
        await self._rebuild_components()
        embed = await self._current_embed()
        await self.panel_message.edit(embed=embed, view=self)

    async def _rebuild_components(self) -> None:
        self.clear_items()

        if self.current_panel == "main":
            self.add_item(self._button("⚠ Warnings", discord.ButtonStyle.secondary, 0, self._go_warnings))
            self.add_item(self._button("🤖 AI Settings", discord.ButtonStyle.primary, 0, self._go_ai))
            self.add_item(self._button("🚨 Raid Controls", discord.ButtonStyle.danger, 0, self._go_raid))
            self.add_item(self._button("📊 Stats", discord.ButtonStyle.secondary, 1, self._go_stats))
            self.add_item(self._button("🔍 Inspect User", discord.ButtonStyle.secondary, 1, self._open_inspect_modal))
            self.add_item(self._button("🔒 Lockdown", discord.ButtonStyle.danger, 1, self._toggle_lockdown_from_main))
            return

        if self.current_panel == "warnings":
            self.add_item(self._button("Add Warning", discord.ButtonStyle.primary, 0, self._open_add_warning_modal))
            self.add_item(self._button("Clear Temp", discord.ButtonStyle.secondary, 0, self._open_clear_temp_modal))
            self.add_item(self._button("Reset All", discord.ButtonStyle.danger, 0, self._open_reset_all_modal))
            self.add_item(self._button("Back", discord.ButtonStyle.secondary, 1, self._go_main))
            return

        if self.current_panel == "ai":
            self.add_item(SensitivitySelect(self))
            self.add_item(self._button("Toggle AI On/Off", discord.ButtonStyle.primary, 1, self._toggle_ai))
            self.add_item(self._button("Set Confidence Threshold", discord.ButtonStyle.secondary, 1, self._set_confidence))
            self.add_item(self._button("Back", discord.ButtonStyle.secondary, 2, self._go_main))
            return

        if self.current_panel == "raid":
            self.add_item(self._button("Enable Lockdown", discord.ButtonStyle.danger, 0, self._enable_lockdown))
            self.add_item(self._button("Disable Lockdown", discord.ButtonStyle.success, 0, self._disable_lockdown))
            self.add_item(self._button("Panic Lock", discord.ButtonStyle.danger, 1, self._panic_lock))
            self.add_item(self._button("Back", discord.ButtonStyle.secondary, 2, self._go_main))
            return

        if self.current_panel == "stats":
            self.add_item(self._button("Back", discord.ButtonStyle.secondary, 0, self._go_main))
            return

        if self.current_panel == "inspect":
            self.add_item(self._button("Timeout 2d", discord.ButtonStyle.danger, 0, self._timeout_user))
            self.add_item(self._button("Clear Risk", discord.ButtonStyle.secondary, 0, self._clear_risk))
            self.add_item(self._button("Back", discord.ButtonStyle.secondary, 1, self._go_main))

    def _button(
        self,
        label: str,
        style: discord.ButtonStyle,
        row: int,
        handler: Callable[[discord.Interaction], Coroutine[None, None, None]],
    ) -> discord.ui.Button[discord.ui.View]:
        button = discord.ui.Button(label=label, style=style, row=row)

        async def _callback(interaction: discord.Interaction) -> None:
            await handler(interaction)

        button.callback = _callback
        return button

    async def _current_embed(self) -> discord.Embed:
        if self.current_panel == "main":
            return await self._build_main_embed()
        if self.current_panel == "warnings":
            return await self._build_warnings_embed()
        if self.current_panel == "ai":
            return await self._build_ai_embed()
        if self.current_panel == "raid":
            return await self._build_raid_embed()
        if self.current_panel == "stats":
            return await self._build_stats_embed()
        return await self._build_user_inspector_embed()

    async def _build_main_embed(self) -> discord.Embed:
        stats = await self.bot.db.get_mod_stats(self.guild_id)
        sensitivity = await self.bot.cache.get_sensitivity(self.guild_id, self.bot.settings.default_sensitivity)
        self.current_sensitivity = sensitivity
        ai_enabled = await self.bot.cache.get_ai_enabled(self.guild_id)
        lockdown = await self.bot.cache.is_lockdown(self.guild_id)

        embed = discord.Embed(title="🛡 AI Moderation Control Center", color=discord.Color.blurple())
        embed.add_field(name="AI Status", value="Enabled" if ai_enabled else "Disabled", inline=True)
        embed.add_field(name="Sensitivity Level", value=f"{sensitivity_to_label(sensitivity)} ({sensitivity:.2f})", inline=True)
        embed.add_field(name="Lockdown Status", value="Active" if lockdown else "Inactive", inline=True)
        embed.add_field(name="Active Temp Warnings", value=str(stats["active_temp"]), inline=True)
        embed.add_field(name="Permanent Warnings", value=str(stats["permanent"]), inline=True)
        embed.add_field(name="Last 24h Infractions", value=str(stats["last_24h"]), inline=True)
        return embed

    async def _build_warnings_embed(self) -> discord.Embed:
        stats = await self.bot.db.get_mod_stats(self.guild_id)
        stage = escalation_stage_description(stats["active_temp"], stats["permanent"])

        embed = discord.Embed(title="⚠ Warnings Panel", color=discord.Color.orange())
        embed.add_field(name="Verbal Count", value=str(stats["verbal"]), inline=True)
        embed.add_field(name="Active Temp Count", value=str(stats["active_temp"]), inline=True)
        embed.add_field(name="Permanent Count", value=str(stats["permanent"]), inline=True)
        embed.add_field(name="Escalation Stage", value=stage, inline=False)
        return embed

    async def _build_ai_embed(self) -> discord.Embed:
        sensitivity = await self.bot.cache.get_sensitivity(self.guild_id, self.bot.settings.default_sensitivity)
        self.current_sensitivity = sensitivity
        ai_enabled = await self.bot.cache.get_ai_enabled(self.guild_id)

        embed = discord.Embed(title="🤖 AI Settings", color=discord.Color.blue())
        embed.add_field(name="AI Status", value="Enabled" if ai_enabled else "Disabled", inline=True)
        embed.add_field(name="Sensitivity", value=f"{sensitivity_to_label(sensitivity)} ({sensitivity:.2f})", inline=True)
        embed.add_field(name="Confidence Threshold", value=f"{sensitivity:.2f}", inline=True)
        return embed

    async def _build_raid_embed(self) -> discord.Embed:
        lockdown = await self.bot.cache.is_lockdown(self.guild_id)
        threshold, window_seconds = await self.bot.cache.get_raid_settings(self.guild_id)

        embed = discord.Embed(title="🚨 Raid Controls", color=discord.Color.red())
        embed.add_field(name="Toxic Burst Threshold", value=f"{threshold} messages", inline=True)
        embed.add_field(name="Time Window", value=f"{window_seconds} seconds", inline=True)
        embed.add_field(name="Lockdown State", value="Enabled" if lockdown else "Disabled", inline=True)
        return embed

    async def _build_stats_embed(self) -> discord.Embed:
        stats = await self.bot.db.get_mod_stats(self.guild_id)
        breakdown = f"Verbal: {stats['verbal']}\nTemp: {stats['temp']}\nPermanent: {stats['permanent']}"
        top_offenders = "\n".join([f"<@{uid}>: {count}" for uid, count in stats["top_users"]]) or "No offenders yet"

        embed = discord.Embed(title="📊 Moderation Stats", color=discord.Color.green())
        embed.add_field(name="Total Infractions", value=str(stats["total"]), inline=True)
        embed.add_field(name="Last 24h Activity", value=str(stats["last_24h"]), inline=True)
        embed.add_field(name="Breakdown by Type", value=breakdown, inline=False)
        embed.add_field(name="Top 5 Offenders", value=top_offenders, inline=False)
        return embed

    async def _build_user_inspector_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🔍 User Inspector", color=discord.Color.gold())
        if self.inspected_user_id is None:
            embed.description = "No user selected."
            return embed

        counts = await self.bot.db.get_warning_counts(self.guild_id, self.inspected_user_id)
        risk = await self.bot.cache.get_risk_score(
            self.guild_id,
            self.inspected_user_id,
            self.bot.settings.risk_decay_per_hour,
        )
        rows = await self.bot.db.get_recent_warnings(self.guild_id, self.inspected_user_id, limit=5)

        if risk >= self.bot.settings.risk_permanent_threshold:
            summary = "Very high risk behavior pattern."
        elif risk >= self.bot.settings.risk_temp_threshold:
            summary = "Escalating risk pattern."
        elif risk > 0:
            summary = "Low-to-moderate risk pattern."
        else:
            summary = "No active risk signal."

        infraction_lines = []
        for row in rows:
            created = row["created_at"].strftime("%m-%d %H:%M")
            infraction_lines.append(f"{created} | {row['warning_type']} | {row['severity']}")
        history = "\n".join(infraction_lines) or "No infractions"

        embed.add_field(name="User", value=f"<@{self.inspected_user_id}> (`{self.inspected_user_id}`)", inline=False)
        embed.add_field(name="Risk Score", value=f"{risk:.2f}", inline=True)
        embed.add_field(
            name="Warning Counts",
            value=f"Verbal: {counts['verbal']} | Temp: {counts['temp']} | Permanent: {counts['permanent']}",
            inline=False,
        )
        embed.add_field(name="Last 5 Infractions", value=history, inline=False)
        embed.add_field(name="AI Behavior Summary", value=summary, inline=False)
        return embed

    async def show_main_panel(self, interaction: discord.Interaction) -> None:
        self.current_panel = "main"
        await self._edit_panel()

    async def show_warnings_panel(self, interaction: discord.Interaction) -> None:
        self.current_panel = "warnings"
        await self._edit_panel()

    async def show_ai_panel(self, interaction: discord.Interaction) -> None:
        self.current_panel = "ai"
        await self._edit_panel()

    async def show_raid_panel(self, interaction: discord.Interaction) -> None:
        self.current_panel = "raid"
        await self._edit_panel()

    async def show_stats_panel(self, interaction: discord.Interaction) -> None:
        self.current_panel = "stats"
        await self._edit_panel()

    async def show_user_inspector_panel(self, interaction: discord.Interaction) -> None:
        self.current_panel = "inspect"
        await self._edit_panel()

    async def _go_main(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.show_main_panel(interaction)

        await self._run_action(interaction, _action)

    async def _go_warnings(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.show_warnings_panel(interaction)

        await self._run_action(interaction, _action)

    async def _go_ai(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.show_ai_panel(interaction)

        await self._run_action(interaction, _action)

    async def _go_raid(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.show_raid_panel(interaction)

        await self._run_action(interaction, _action)

    async def _go_stats(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.show_stats_panel(interaction)

        await self._run_action(interaction, _action)

    async def _toggle_lockdown_from_main(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            current = await self.bot.cache.is_lockdown(self.guild_id)
            await self.bot.cache.set_lockdown(self.guild_id, not current)
            await self.show_main_panel(interaction)
            await interaction.followup.send(f"Lockdown {'enabled' if not current else 'disabled'}.", ephemeral=True)

        await self._run_action(interaction, _action)

    async def _open_add_warning_modal(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.send_modal(AddWarningModal(self))

        await self._run_action(interaction, _action)

    async def _open_clear_temp_modal(self, interaction: discord.Interaction) -> None:
        async def _clear(inter: discord.Interaction, user_id: int) -> None:
            try:
                await inter.response.defer(ephemeral=True)
                removed = await self.bot.db.clear_temp_warnings(self.guild_id, user_id)
                await self.show_warnings_panel(inter)
                await inter.followup.send(f"Cleared `{removed}` active temp warnings for `<@{user_id}>`.", ephemeral=True)
            except Exception as exc:
                await self.send_error(inter, exc)

        async def _action() -> None:
            await interaction.response.send_modal(UserIdModal("Clear Temp Warnings", _clear))

        await self._run_action(interaction, _action)

    async def _open_reset_all_modal(self, interaction: discord.Interaction) -> None:
        async def _reset(inter: discord.Interaction, user_id: int) -> None:
            try:
                await inter.response.defer(ephemeral=True)
                removed = await self.bot.db.reset_all_warnings(self.guild_id, user_id)
                await self.bot.cache.clear_risk_score(self.guild_id, user_id)
                await self.show_warnings_panel(inter)
                await inter.followup.send(f"Reset `{removed}` warning records and cleared risk for `<@{user_id}>`.", ephemeral=True)
            except Exception as exc:
                await self.send_error(inter, exc)

        async def _action() -> None:
            await interaction.response.send_modal(UserIdModal("Reset All Warnings", _reset))

        await self._run_action(interaction, _action)

    async def _toggle_ai(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            enabled = await self.bot.cache.get_ai_enabled(self.guild_id)
            await self.bot.cache.set_ai_enabled(self.guild_id, not enabled)
            await self.show_ai_panel(interaction)
            await interaction.followup.send(f"AI moderation {'enabled' if not enabled else 'disabled'}.", ephemeral=True)

        await self._run_action(interaction, _action)

    async def _set_confidence(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.send_modal(ConfidenceThresholdModal(self))

        await self._run_action(interaction, _action)

    async def _enable_lockdown(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.bot.cache.set_lockdown(self.guild_id, True)
            await self.show_raid_panel(interaction)
            await interaction.followup.send("Lockdown enabled.", ephemeral=True)

        await self._run_action(interaction, _action)

    async def _disable_lockdown(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.bot.cache.set_lockdown(self.guild_id, False)
            await self.show_raid_panel(interaction)
            await interaction.followup.send("Lockdown disabled.", ephemeral=True)

        await self._run_action(interaction, _action)

    async def _panic_lock(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.defer(ephemeral=True)
            await self.bot.cache.set_lockdown(self.guild_id, True)
            await self.bot.cache.set_raid_settings(self.guild_id, threshold=4, window_seconds=10)
            await self.show_raid_panel(interaction)
            await interaction.followup.send("Panic Lock activated: lockdown enabled and raid sensitivity tightened.", ephemeral=True)

        await self._run_action(interaction, _action)

    async def _open_inspect_modal(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            await interaction.response.send_modal(InspectUserModal(self))

        await self._run_action(interaction, _action)

    async def _timeout_user(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            if self.inspected_user_id is None:
                await interaction.response.send_message("Inspect a user first.", ephemeral=True)
                return

            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("Guild-only action.", ephemeral=True)
                return

            member = guild.get_member(self.inspected_user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(self.inspected_user_id)
                except discord.HTTPException:
                    member = None

            if member is None:
                await interaction.response.send_message("User not found in this guild.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            me = guild.me
            if me is None or not me.guild_permissions.moderate_members:
                await interaction.followup.send("Bot lacks Moderate Members permission.", ephemeral=True)
                return
            if guild.owner_id == member.id or member.top_role >= me.top_role:
                await interaction.followup.send("Cannot timeout this user due to role hierarchy.", ephemeral=True)
                return

            until = discord.utils.utcnow() + timedelta(days=2)
            await member.timeout(until, reason=f"Applied from moderation panel by {interaction.user}")
            await self.show_user_inspector_panel(interaction)
            await interaction.followup.send(f"Applied 2-day timeout to {member.mention}.", ephemeral=True)

        await self._run_action(interaction, _action)

    async def _clear_risk(self, interaction: discord.Interaction) -> None:
        async def _action() -> None:
            if self.inspected_user_id is None:
                await interaction.response.send_message("Inspect a user first.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            await self.bot.cache.clear_risk_score(self.guild_id, self.inspected_user_id)
            await self.show_user_inspector_panel(interaction)
            await interaction.followup.send("Risk score cleared.", ephemeral=True)

        await self._run_action(interaction, _action)


class ModerationPanel(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="panel", description="Open the AI moderation control center")
    async def panel(self, interaction: discord.Interaction) -> None:
        try:
            if not interaction.guild or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("Guild-only command.", ephemeral=True)
                return

            if not interaction.user.guild_permissions.manage_messages:
                await interaction.response.send_message("Manage Messages permission required.", ephemeral=True)
                return

            view = ModerationPanelView(self.bot, interaction.guild.id)
            embed = await view.initialize()
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.panel_message = await interaction.original_response()
        except Exception as exc:
            logger.exception("Failed to open moderation panel")
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Unable to open moderation panel due to an internal error.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Unable to open moderation panel due to an internal error.",
                    ephemeral=True,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationPanel(bot))
