from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import discord
from discord.ext import commands

from .anti_spam import AntiSpam
from .cache import Cache
from .config import Settings, load_settings
from .database import Database
from .groq_client import GroqClient
from .moderation_engine import ModerationEngine
from .reinforcement import ReinforcementEngine
from .utils import Action, ModerationResult, Severity, setup_structured_logging

logger = logging.getLogger(__name__)


def _action_rank(action: Action) -> int:
    return {
        Action.NONE: 0,
        Action.WARN: 1,
        Action.DELETE: 2,
        Action.TIMEOUT: 3,
        Action.KICK: 4,
        Action.BAN: 5,
    }[action]


def _severity_base_action(severity: Severity) -> Action:
    return {
        Severity.SAFE: Action.NONE,
        Severity.WARNING: Action.WARN,
        Severity.TOXIC: Action.WARN,
        Severity.NSFW: Action.DELETE,
        Severity.SPAM: Action.DELETE,
        Severity.SEVERE: Action.TIMEOUT,
        Severity.HATE: Action.KICK,
        Severity.THREAT: Action.BAN,
    }[severity]


class ModerationBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.settings = settings
        self.db = Database(settings.database_url)
        self.cache = Cache(settings.redis_url)
        self.groq = GroqClient(settings.groq_api_key, settings.groq_model, settings.moderation_timeout_seconds)
        self.anti_spam = AntiSpam(
            cache=self.cache,
            spam_window_seconds=settings.spam_window_seconds,
            spam_burst_count=settings.spam_burst_count,
            raid_window_seconds=settings.raid_window_seconds,
            raid_toxic_threshold=settings.raid_toxic_threshold,
        )
        self.reinforcement = ReinforcementEngine(
            cache=self.cache,
            db=self.db,
            decay_per_hour=settings.risk_decay_per_hour,
        )
        self.moderation = ModerationEngine(settings, self.groq, self.cache, self.anti_spam)

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

    async def close(self) -> None:
        await self.groq.close()
        await self.cache.close()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Bot connected as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        # Pipeline: analyze -> risk/reinforcement -> choose action -> execute -> persist log -> raid defense.
        if not message.guild or not message.author or message.author.bot:
            return
        if not message.content.strip():
            return

        author = message.author
        if isinstance(author, discord.Member) and (
            author.guild_permissions.administrator or author.guild_permissions.manage_messages
        ):
            return

        result = await self.moderation.analyze_message(message.guild.id, author.id, message.content)

        risk_score = await self.reinforcement.get_risk(message.guild.id, author.id)
        if result.severity != Severity.SAFE:
            risk_score = await self.reinforcement.apply_infraction(
                message.guild.id, author.id, result.severity, len(result.bypass_flags)
            )

        previous_infractions = await self.db.get_user_infraction_count(message.guild.id, author.id)
        action = self._determine_action(result, risk_score, previous_infractions)
        executed_action = await self._apply_action(message, author, result, action)

        await self.db.log_infraction(
            {
                "guild_id": message.guild.id,
                "channel_id": message.channel.id,
                "message_id": message.id,
                "user_id": author.id,
                "severity": result.severity.value,
                "confidence": result.confidence,
                "action_taken": executed_action.value,
                "reasoning": result.reasoning,
                "normalized_content": result.normalized_text,
                "bypass_flags": result.bypass_flags,
                "risk_score": risk_score,
            }
        )

        if result.severity in {Severity.TOXIC, Severity.SEVERE, Severity.HATE, Severity.THREAT, Severity.SPAM}:
            await self._maybe_trigger_lockdown(message, result)

    def _determine_action(
        self, result: ModerationResult, risk_score: float, previous_infractions: int
    ) -> Action:
        base = _severity_base_action(result.severity)
        action = result.recommended_action if _action_rank(result.recommended_action) > _action_rank(base) else base

        if risk_score >= self.settings.risk_ban_threshold:
            action = Action.BAN
        elif risk_score >= self.settings.risk_kick_threshold:
            action = max(action, Action.KICK, key=_action_rank)
        elif risk_score >= self.settings.risk_timeout_threshold:
            action = max(action, Action.TIMEOUT, key=_action_rank)
        elif risk_score >= self.settings.risk_delete_threshold:
            action = max(action, Action.DELETE, key=_action_rank)
        elif risk_score >= self.settings.risk_warn_threshold:
            action = max(action, Action.WARN, key=_action_rank)

        if previous_infractions >= 10:
            action = max(action, Action.BAN, key=_action_rank)
        elif previous_infractions >= 6:
            action = max(action, Action.KICK, key=_action_rank)
        elif previous_infractions >= 3:
            action = max(action, Action.TIMEOUT, key=_action_rank)

        return action

    async def _apply_action(
        self,
        message: discord.Message,
        member: discord.Member,
        result: ModerationResult,
        action: Action,
    ) -> Action:
        me = message.guild.me
        if not me:
            return Action.NONE

        if action in {Action.KICK, Action.BAN, Action.TIMEOUT}:
            if message.guild.owner_id == member.id or member.top_role >= me.top_role:
                action = Action.DELETE if action in {Action.KICK, Action.BAN, Action.TIMEOUT} else action

        try:
            if action in {Action.DELETE, Action.TIMEOUT, Action.KICK, Action.BAN}:
                if message.channel.permissions_for(me).manage_messages:
                    await message.delete()

            if action == Action.WARN:
                await message.channel.send(
                    f"{member.mention} warning: {result.reasoning[:120]}",
                    delete_after=10,
                )
                return Action.WARN

            if action == Action.TIMEOUT and me.guild_permissions.moderate_members:
                until = datetime.now(UTC) + timedelta(minutes=self.settings.default_timeout_minutes)
                await member.edit(timed_out_until=until, reason=f"AI moderation: {result.severity.value}")
                return Action.TIMEOUT

            if action == Action.KICK and me.guild_permissions.kick_members:
                await member.kick(reason=f"AI moderation: {result.severity.value}")
                return Action.KICK

            if action == Action.BAN and me.guild_permissions.ban_members:
                await member.ban(reason=f"AI moderation: {result.severity.value}", delete_message_seconds=3600)
                return Action.BAN

            if action == Action.DELETE:
                return Action.DELETE

            return Action.NONE
        except discord.Forbidden:
            logger.warning("Permission denied while applying moderation action")
            return Action.NONE
        except discord.HTTPException:
            logger.exception("Discord API error while applying moderation action")
            return Action.NONE

    async def _maybe_trigger_lockdown(self, message: discord.Message, result: ModerationResult) -> None:
        # Anti-raid mode auto-locks the channel when toxic volume exceeds threshold/window.
        if not await self.anti_spam.is_lockdown_enabled(message.guild.id):
            return

        threshold, window = await self.anti_spam.get_raid_threshold(message.guild.id)

        raid_detected = await self.anti_spam.mark_toxic_and_check_raid(
            message.guild.id, message.channel.id, threshold=threshold, window=window
        )
        if not raid_detected:
            return

        lock_key = f"lockdown:channel:{message.guild.id}:{message.channel.id}"
        first_trigger = await self.cache.set_if_not_exists(lock_key, "1", ex=window)
        if not first_trigger:
            return

        me = message.guild.me
        if not me or not message.channel.permissions_for(me).manage_channels:
            return

        overwrite = message.channel.overwrites_for(message.guild.default_role)
        overwrite.send_messages = False
        await message.channel.set_permissions(
            message.guild.default_role,
            overwrite=overwrite,
            reason="Anti-raid lockdown triggered",
        )
        await self.db.log_lockdown_event(
            message.guild.id,
            message.channel.id,
            True,
            f"Auto-lockdown: {threshold} toxic msgs/{window}s",
        )
        await message.channel.send(
            "Channel temporarily locked due to raid detection. Moderators can restore permissions.",
            delete_after=30,
        )


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
        logger.info("Shutting down moderation bot")


if __name__ == "__main__":
    run()
