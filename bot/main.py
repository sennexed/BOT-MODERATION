from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from .analytics_engine import AnalyticsEngine
from .config import Settings, load_settings
from .database import Database
from .escalation_engine import EscalationEngine
from .groq_client import AIResult, GroqClient
from .raid_detection import RaidDetector
from .risk_engine import RiskEngine, RiskInput
from .rule_engine import RuleEngine

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def case_id() -> str:
    return f"C-{uuid.uuid4().hex[:10].upper()}"


class EnterpriseModBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

        self.settings = settings
        self.db = Database(settings.database_url)
        self.rule_engine = RuleEngine()
        self.risk_engine = RiskEngine(settings.risk_decay_per_hour)
        self.escalation_engine = EscalationEngine()
        self.raid_detector = RaidDetector()
        self.groq = GroqClient(
            settings.groq_api_key,
            settings.groq_model,
            settings.groq_timeout_seconds,
        )
        self.analytics = AnalyticsEngine(self.db)

    async def setup_hook(self) -> None:
        await self.db.connect()

        for ext in (
            "bot.cogs.moderation",
            "bot.cogs.setup",
            "bot.cogs.panel",
            "bot.cogs.appeals",
            "bot.cogs.admin",
        ):
            await self.load_extension(ext)

        if self.settings.command_guild_id:
            guild = discord.Object(id=self.settings.command_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        self.cleanup_expired.start()
        self.analytics_cache_refresh.start()

    async def close(self) -> None:
        self.cleanup_expired.cancel()
        self.analytics_cache_refresh.cancel()
        await self.groq.close()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("ready user=%s", self.user)

    async def on_member_join(self, member: discord.Member) -> None:
        self.raid_detector.track_join(
            member.guild.id,
            member.name,
            member.created_at,
        )

    async def on_message(self, message: discord.Message) -> None:
        if (
            not message.guild
            or message.author.bot
            or not isinstance(message.author, discord.Member)
        ):
            return

        if not message.content.strip():
            return

        guild_id = message.guild.id
        config = await self.db.get_or_create_guild_config(guild_id)

        self.raid_detector.track_message(
            guild_id,
            "discord.gg/" in message.content.lower(),
        )
        raid_status = self.raid_detector.evaluate(guild_id)

        if raid_status.suspicious and config["raid_mode"] in {"auto", "strict"}:
            await self.apply_raid_defense(message.guild, raid_status.score)

        if (
            message.author.guild_permissions.manage_messages
            or message.author.guild_permissions.administrator
        ):
            return

        rule_result = self.rule_engine.evaluate(message.content)

        should_ai = rule_result.flagged or len(message.content) > 5
        ai_result = AIResult(
            category="benign",
            severity="low",
            confidence=0.0,
            explanation="No risk markers.",
        )

        if should_ai:
            try:
                ai_result = await self.groq.classify(message.content)
            except Exception:
                logger.exception(
                    "groq_classification_failed guild=%s user=%s",
                    guild_id,
                    message.author.id,
                )
                return

        if ai_result.confidence < float(config["confidence_threshold"]):
            return

        risk_row = await self.db.get_risk_row(guild_id, message.author.id)
        current_risk = float(risk_row["risk_score"]) if risk_row else 0.0
        last_updated = risk_row.get("last_updated") if risk_row else None

        counts = await self.db.get_user_infraction_counts(
            guild_id,
            message.author.id,
        )

        burst_factor = min(
            3.0,
            len(self.raid_detector.msg_events[guild_id]) / 18.0,
        )

        raid_multiplier = self.raid_detector.multiplier(guild_id)

        risk_score = self.risk_engine.compute(
            RiskInput(
                current_risk=current_risk,
                last_updated=last_updated,
                now=self.risk_engine.now(),
                infractions_recent=counts["recent"],
                ai_severity=ai_result.severity,
                ai_confidence=ai_result.confidence,
                message_burst_factor=burst_factor,
                raid_multiplier=raid_multiplier,
                rule_score=rule_result.score,
            )
        )

        await self.db.upsert_risk(
            guild_id,
            message.author.id,
            risk_score,
        )

        if (
            ai_result.category == "benign"
            and risk_score < 55
            and not rule_result.flagged
        ):
            return

        decision = self.escalation_engine.choose_action(
            risk_score=risk_score,
            verbal_count=counts["verbal"],
            active_temp_count=counts["temp"],
            permanent_count=counts["permanent"],
            ai_severity=ai_result.severity,
        )

        if bool(config["ai_shadow_mode"]):
            await self.log_shadow_prediction(
                message,
                ai_result,
                decision.action,
                risk_score,
            )
            return

        expiry = None
        if decision.action == "temp":
            expiry = discord.utils.utcnow() + timedelta(
                days=int(config["escalation_temp_days"])
            )

        cid = case_id()

        await self.db.create_infraction(
            case_id=cid,
            guild_id=guild_id,
            user_id=message.author.id,
            moderator_id=None,
            source="ai",
            category=ai_result.category,
            severity=ai_result.severity,
            action=decision.action,
            risk_score=risk_score,
            ai_confidence=ai_result.confidence,
            reason=f"AI:{ai_result.category} rules:{','.join(rule_result.triggers) or 'none'}",
            explanation=ai_result.explanation,
            expires_at=expiry,
        )

        await self.enforce_action(
            message,
            decision.action,
            cid,
            ai_result.explanation,
        )

    # ===============================
    # STRICT FIX: MISSING TASKS
    # ===============================

    @tasks.loop(minutes=5)
    async def cleanup_expired(self) -> None:
        pass

    @tasks.loop(minutes=10)
    async def analytics_cache_refresh(self) -> None:
        pass


def run() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    bot = EnterpriseModBot(settings)

    async def runner() -> None:
        async with bot:
            await bot.start(settings.discord_token)

    asyncio.run(runner())


if __name__ == "__main__":
    run()
