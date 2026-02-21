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
        self.groq = GroqClient(settings.groq_api_key, settings.groq_model, settings.groq_timeout_seconds)
        self.analytics = AnalyticsEngine(self.db)

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.db.init_schema()

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
        self.raid_detector.track_join(member.guild.id, member.name, member.created_at)

    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if not message.content.strip():
            return

        guild_id = message.guild.id
        config = await self.db.get_or_create_guild_config(guild_id)

        self.raid_detector.track_message(guild_id, "discord.gg/" in message.content.lower())
        raid_status = self.raid_detector.evaluate(guild_id)

        if raid_status.suspicious and config["raid_mode"] in {"auto", "strict"}:
            await self.apply_raid_defense(message.guild, raid_status.score)

        if message.author.guild_permissions.manage_messages or message.author.guild_permissions.administrator:
            return

        rule_result = self.rule_engine.evaluate(message.content)

        should_ai = rule_result.flagged or len(message.content) > 5
        ai_result = AIResult(category="benign", severity="low", confidence=0.0, explanation="No risk markers.")
        if should_ai:
            try:
                ai_result = await self.groq.classify(message.content)
            except Exception:
                logger.exception("groq_classification_failed guild=%s user=%s", guild_id, message.author.id)
                return

        if ai_result.confidence < float(config["confidence_threshold"]):
            return

        risk_row = await self.db.get_risk_row(guild_id, message.author.id)
        current_risk = float(risk_row["risk_score"]) if risk_row else 0.0
        last_updated = risk_row["last_updated"] if risk_row else None

        counts = await self.db.get_user_infraction_counts(guild_id, message.author.id)
        burst_factor = min(3.0, len(self.raid_detector.msg_events[guild_id]) / 18.0)
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
        await self.db.upsert_risk(guild_id, message.author.id, risk_score)

        if ai_result.category == "benign" and risk_score < 55 and not rule_result.flagged:
            return

        decision = self.escalation_engine.choose_action(
            risk_score=risk_score,
            verbal_count=counts["verbal"],
            active_temp_count=counts["temp"],
            permanent_count=counts["permanent"],
            ai_severity=ai_result.severity,
        )

        if bool(config["ai_shadow_mode"]):
            await self.log_shadow_prediction(message, ai_result, decision.action, risk_score)
            return

        expiry = None
        if decision.action == "temp":
            expiry = self.db.now() + timedelta(days=int(config["escalation_temp_days"]))

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

        await self.enforce_action(message, decision.action, cid, ai_result.explanation)

    async def log_shadow_prediction(
        self,
        message: discord.Message,
        ai: AIResult,
        action: str,
        risk_score: int,
    ) -> None:
        embed = discord.Embed(title="Shadow Moderation Prediction", color=discord.Color.blurple())
        embed.add_field(name="User", value=message.author.mention, inline=True)
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Risk", value=str(risk_score), inline=True)
        embed.add_field(name="AI", value=f"{ai.category}/{ai.severity} ({ai.confidence:.2f})", inline=False)
        embed.description = ai.explanation
        log_channel = await self.get_log_channel(message.guild)
        if log_channel:
            await log_channel.send(embed=embed)

    async def enforce_action(self, message: discord.Message, action: str, cid: str, reason: str) -> None:
        guild = message.guild
        assert guild is not None
        member = message.author
        me = guild.me

        if me is None:
            return

        if action == "verbal":
            embed = discord.Embed(title="Policy Warning", description=reason, color=discord.Color.orange())
            embed.add_field(name="Case ID", value=cid)
            try:
                await member.send(embed=embed)
            except discord.HTTPException:
                pass
        elif action == "temp":
            if me.guild_permissions.manage_messages:
                await message.delete()
            if me.guild_permissions.moderate_members and member.top_role < me.top_role:
                until = discord.utils.utcnow() + timedelta(days=1)
                await member.timeout(until, reason=f"Temp moderation case {cid}")
        elif action == "permanent":
            if me.guild_permissions.manage_messages:
                await message.delete()
        elif action == "timeout":
            if me.guild_permissions.moderate_members and member.top_role < me.top_role:
                until = discord.utils.utcnow() + timedelta(hours=48)
                await member.timeout(until, reason=f"Auto-timeout {cid}")
        elif action == "ban":
            if me.guild_permissions.ban_members and member.top_role < me.top_role:
                await guild.ban(member, reason=f"AI extreme severity case {cid}", delete_message_days=1)

        embed = discord.Embed(title="Moderation Action", color=discord.Color.red())
        embed.add_field(name="Case", value=cid)
        embed.add_field(name="Action", value=action)
        embed.add_field(name="User", value=member.mention)
        embed.description = reason
        channel = await self.get_log_channel(guild)
        if channel:
            await channel.send(embed=embed)

    async def apply_raid_defense(self, guild: discord.Guild, score: float) -> None:
        await self.db.update_guild_config(guild.id, strict_ai_enabled=True)
        for channel in guild.text_channels[:8]:
            perms = channel.permissions_for(guild.me) if guild.me else None
            if perms and perms.manage_channels:
                slowmode = 10 if score < 1.7 else 20
                try:
                    await channel.edit(slowmode_delay=slowmode, reason="Auto raid defense")
                except discord.HTTPException:
                    continue
        if guild.me and guild.me.guild_permissions.manage_guild:
            try:
                await guild.edit(verification_level=discord.VerificationLevel.high, reason="Restricting new members during raid defense")
            except discord.HTTPException:
                pass
        if score >= 1.8:
            for channel in guild.text_channels[:3]:
                perms = channel.permissions_for(guild.me) if guild.me else None
                if not perms or not perms.manage_channels:
                    continue
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = False
                try:
                    await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="Auto raid lock")
                except discord.HTTPException:
                    continue
        log_channel = await self.get_log_channel(guild)
        if log_channel:
            embed = discord.Embed(title="Raid Defense Activated", color=discord.Color.dark_red())
            embed.description = f"Automated raid defense enabled. Score: {score:.2f}"
            await log_channel.send(embed=embed)

    async def get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = await self.db.get_or_create_guild_config(guild.id)
        log_channel_id = config["log_channel_id"]
        if log_channel_id:
            ch = guild.get_channel(int(log_channel_id))
            if isinstance(ch, discord.TextChannel):
                return ch
        return guild.system_channel if isinstance(guild.system_channel, discord.TextChannel) else None

    @tasks.loop(hours=1)
    async def cleanup_expired(self) -> None:
        expired = await self.db.cleanup_expired_infractions()
        cleaned = await self.db.auto_expire_old_cases()
        if expired or cleaned:
            logger.info("cleanup expired=%s verbal_archived=%s", expired, cleaned)

    @cleanup_expired.before_loop
    async def before_cleanup(self) -> None:
        await self.wait_until_ready()

    @tasks.loop(minutes=30)
    async def analytics_cache_refresh(self) -> None:
        for guild in self.guilds:
            try:
                await self.analytics.snapshot(guild.id)
            except Exception:
                logger.exception("analytics_snapshot_failed guild=%s", guild.id)

    @analytics_cache_refresh.before_loop
    async def before_analytics(self) -> None:
        await self.wait_until_ready()


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
