from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EnterpriseModBot


class AppealsCog(commands.Cog):
    def __init__(self, bot: EnterpriseModBot) -> None:
        self.bot = bot

    appeal_group = app_commands.Group(name="appeal", description="Appeals workflow")

    @appeal_group.command(name="submit", description="Submit an appeal by case ID")
    async def submit(self, interaction: discord.Interaction, case_id: str) -> None:
        assert interaction.guild
        case = await self.bot.db.get_case(interaction.guild.id, case_id)
        if not case or int(case["user_id"]) != interaction.user.id:
            await interaction.response.send_message(embed=discord.Embed(title="Case Not Eligible", description="You can only appeal your own case.", color=discord.Color.red()), ephemeral=True)
            return
        await self.bot.db.create_appeal(interaction.guild.id, interaction.user.id, interaction.user.id, case_id)
        await interaction.response.send_message(embed=discord.Embed(title="Appeal Submitted", description=f"Case `{case_id}` queued for review.", color=discord.Color.green()), ephemeral=True)

    @appeal_group.command(name="review", description="Review an appeal")
    async def review(self, interaction: discord.Interaction, appeal_id: int) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(embed=discord.Embed(title="Permission Denied", color=discord.Color.red()), ephemeral=True)
            return
        appeals = await self.bot.db.list_appeals(interaction.guild.id)
        match = next((a for a in appeals if int(a["id"]) == appeal_id), None)
        if not match:
            await interaction.response.send_message(embed=discord.Embed(title="Appeal Not Found", color=discord.Color.red()), ephemeral=True)
            return
        embed = discord.Embed(title=f"Appeal #{appeal_id}", color=discord.Color.blurple())
        embed.add_field(name="Case", value=str(match["case_id"]))
        embed.add_field(name="User", value=f"<@{int(match['user_id'])}>")
        embed.add_field(name="Status", value=str(match["status"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @appeal_group.command(name="approve", description="Approve an appeal")
    async def approve(self, interaction: discord.Interaction, appeal_id: int, note: str) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(embed=discord.Embed(title="Permission Denied", color=discord.Color.red()), ephemeral=True)
            return
        appeal = await self.bot.db.review_appeal(appeal_id, interaction.guild.id, interaction.user.id, "approved", note)
        if not appeal:
            await interaction.response.send_message(embed=discord.Embed(title="Appeal Not Found", color=discord.Color.red()), ephemeral=True)
            return
        await self.bot.db.set_case_active(interaction.guild.id, str(appeal["case_id"]), False)
        await self.bot.db.log_moderator_action(interaction.guild.id, interaction.user.id, "appeal_approved", str(appeal["case_id"]), {"appeal_id": appeal_id, "note": note})
        await interaction.response.send_message(embed=discord.Embed(title="Appeal Approved", description=f"Case `{appeal['case_id']}` deactivated.", color=discord.Color.green()))

    @appeal_group.command(name="deny", description="Deny an appeal")
    async def deny(self, interaction: discord.Interaction, appeal_id: int, note: str) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(embed=discord.Embed(title="Permission Denied", color=discord.Color.red()), ephemeral=True)
            return
        appeal = await self.bot.db.review_appeal(appeal_id, interaction.guild.id, interaction.user.id, "denied", note)
        if not appeal:
            await interaction.response.send_message(embed=discord.Embed(title="Appeal Not Found", color=discord.Color.red()), ephemeral=True)
            return
        await self.bot.db.log_moderator_action(interaction.guild.id, interaction.user.id, "appeal_denied", str(appeal["case_id"]), {"appeal_id": appeal_id, "note": note})
        await interaction.response.send_message(embed=discord.Embed(title="Appeal Denied", description=f"Case `{appeal['case_id']}` remains active.", color=discord.Color.orange()))

    @appeal_group.command(name="list", description="List appeals")
    async def list_appeals(self, interaction: discord.Interaction, status: str | None = None) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(embed=discord.Embed(title="Permission Denied", color=discord.Color.red()), ephemeral=True)
            return
        rows = await self.bot.db.list_appeals(interaction.guild.id, status)
        embed = discord.Embed(title="Appeals", color=discord.Color.dark_teal())
        if not rows:
            embed.description = "No appeals found."
        else:
            lines = [f"`#{int(r['id'])}` case `{r['case_id']}` status `{r['status']}` by <@{int(r['requested_by'])}>" for r in rows[:20]]
            embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: EnterpriseModBot) -> None:
    await bot.add_cog(AppealsCog(bot))
