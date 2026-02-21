from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from .cache import Cache
from .config import Settings, load_settings
from .database import Database
from .groq_client import GroqClient
from .moderation_engine import ModerationEngine
from .utils import RecommendedAction, setup_structured_logging

logger = logging.getLogger(__name__)


def _risk_delta(action: RecommendedAction) -> float:
    return {
        RecommendedAction.NONE: 0.0,
        RecommendedAction.VERBAL: 0.5,
        RecommendedAction.TEMP: 2.0,
        RecommendedAction.PERMANENT: 4.0,
    }[action]


class ModerationBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.settings = settings
        self.db = Database(settings.database_url)
        self.cache = Cache(settings.redis_url)
        self.groq = GroqClient(settings.groq_api_key, settings.groq_model, settings.groq_timeout_seconds)
        self.moderation = ModerationEngine(settings, self.groq, self.cache)

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.db.initialize_schema()

        await self.load_extension("bot.cogs.moderation_commands")
        await self.load_extension("bot.cogs.admin_commands")

        if self.settings.command_guild_id:
            guild = discord.Object(id=self.settings.command_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        self.cleanup_expired_warnings.start()

    async def close(self) -> None:
        self.cleanup_expired_warnings.cancel()
        await self.groq.close()
        await self.cache.close()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Bot online as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or not isinstance(message.author, discord.Member):
            return
        if message.author.bot:
            return
        if not message.content.strip():
            return

        # Avoid moderating privileged members.
        if message.author.guild_permissions.manage_messages or message.author.guild_permissions.administrator:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        if await self.cache.is_lockdown(guild_id):
            if message.guild.me and message.channel.permissions_for(message.guild.me).manage_messages:
                await message.delete()
            return

        confidence_threshold = await self.cache.get_sensitivity(guild_id, self.settings.default_sensitivity)
        counts = await self.db.get_warning_counts(guild_id, user_id)
        risk_score = await self.cache.get_risk_score(guild_id, user_id, self.settings.risk_decay_per_hour)

        try:
            decision = await self.moderation.moderate_message(
                guild_id=guild_id,
                user_id=user_id,
                content=message.content,
                confidence_threshold=confidence_threshold,
                active_temp_count=counts["temp"],
                permanent_count=counts["permanent"],
                risk_score=risk_score,
            )
        except Exception:
            logger.exception("Moderation analysis failed")
            return

        logger.info(
            "ai_moderation guild=%s user=%s severity=%s confidence=%.3f action=%s reason=%s flags=%s",
            guild_id,
            user_id,
            decision.severity.value,
            decision.confidence,
            decision.action.value,
            decision.reasoning,
            ",".join(decision.bypass_flags) if decision.bypass_flags else "none",
        )

        if decision.action == RecommendedAction.NONE:
            await self.cache.increment_risk_score(guild_id, user_id, -0.05, self.settings.risk_decay_per_hour)
            return

        expires_at = None
        warning_type = decision.action.value
        if decision.action == RecommendedAction.TEMP:
            expires_at = self.db.utcnow() + timedelta(days=self.settings.temp_warning_days)

        await self.db.add_infraction(
            guild_id=guild_id,
            user_id=user_id,
            warning_type=warning_type,
            severity=decision.severity.value,
            reason=decision.reasoning,
            confidence=decision.confidence,
            expires_at=expires_at,
        )

        if decision.action == RecommendedAction.VERBAL:
            await self._send_verbal_warning(message.author, decision.reasoning)
        else:
            if message.guild.me and message.channel.permissions_for(message.guild.me).manage_messages:
                await message.delete()

        if decision.action == RecommendedAction.TEMP:
            promoted = await self.db.promote_temp_to_permanent_if_needed(guild_id, user_id)
            if promoted:
                logger.info("temp_to_permanent_conversion guild=%s user=%s", guild_id, user_id)

        permanent_count = await self.db.get_permanent_warning_count(guild_id, user_id)
        if permanent_count >= 5:
            await self._apply_auto_timeout(message.guild, message.author, permanent_count)

        await self.cache.increment_risk_score(
            guild_id,
            user_id,
            _risk_delta(decision.action),
            self.settings.risk_decay_per_hour,
        )

    async def _send_verbal_warning(self, member: discord.Member, reason: str) -> None:
        try:
            await member.send(f"Verbal warning from moderation system: {reason[:300]}")
        except discord.HTTPException:
            logger.info("Unable to DM verbal warning to user=%s", member.id)

    async def _apply_auto_timeout(self, guild: discord.Guild, member: discord.Member, permanent_count: int) -> None:
        me = guild.me
        if me is None:
            return
        if not me.guild_permissions.moderate_members:
            return
        if guild.owner_id == member.id or member.top_role >= me.top_role:
            logger.warning("Cannot timeout user due to role hierarchy guild=%s user=%s", guild.id, member.id)
            return

        until = discord.utils.utcnow() + timedelta(hours=self.settings.timeout_hours)
        reason = (
            f"Automatic timeout: {permanent_count} permanent warnings "
            f"(policy threshold: 5)"
        )
        try:
            await member.timeout(until, reason=reason)
            await self._notify_moderators(guild, f"Auto-timeout applied to {member.mention} for 48 hours ({permanent_count} permanent warnings).")
            logger.info("auto_timeout guild=%s user=%s permanent_count=%s", guild.id, member.id, permanent_count)
        except discord.HTTPException:
            logger.exception("Failed to apply automatic timeout")

    async def _notify_moderators(self, guild: discord.Guild, content: str) -> None:
        channel = None
        if self.settings.mod_alert_channel_id:
            channel = guild.get_channel(self.settings.mod_alert_channel_id)

        if channel is None:
            channel = guild.system_channel

        if channel and isinstance(channel, discord.TextChannel):
            try:
                await channel.send(content)
            except discord.HTTPException:
                logger.warning("Failed to notify moderators in guild=%s", guild.id)

    @tasks.loop(hours=24)
    async def cleanup_expired_warnings(self) -> None:
        removed = await self.db.cleanup_expired_temp_warnings()
        logger.info("expired_temp_cleanup removed=%s", removed)

    @cleanup_expired_warnings.before_loop
    async def before_cleanup(self) -> None:
        await self.wait_until_ready()


def run() -> None:
    settings = load_settings()
    setup_structured_logging(settings.log_level)

    bot = ModerationBot(settings)

    async def _runner() -> None:
        async with bot:
            await bot.start(settings.discord_token)

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")


if __name__ == "__main__":
    run()
