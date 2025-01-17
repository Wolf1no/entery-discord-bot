import discord
from discord.ext import commands, tasks
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
import asyncio
import os
import json
import logging
import traceback
from typing import Optional, Dict

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from GitHub Secrets
TWITCH_CLIENT_ID = os.environ['TWITCH_CLIENT_ID']
TWITCH_CLIENT_SECRET = os.environ['TWITCH_CLIENT_SECRET']
DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
TWITCH_CHANNEL_NAME = os.environ['TWITCH_CHANNEL_NAME']
DISCORD_GUILD_ID = int(os.environ['DISCORD_GUILD_ID'])
DISCORD_VIP_ROLE_ID = int(os.environ['DISCORD_VIP_ROLE_ID'])
DISCORD_SUB_ROLE_ID = int(os.environ.get('DISCORD_SUB_ROLE_ID', 0))  # Optional subscriber role

# File paths
VERIFIED_USERS_FILE = 'verified_users.json'

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
twitch = None
verified_users: Dict[str, str] = {}

def load_verified_users():
    global verified_users
    try:
        if os.path.exists(VERIFIED_USERS_FILE):
            with open(VERIFIED_USERS_FILE, 'r') as f:
                verified_users = json.load(f)
            logger.info(f"Loaded {len(verified_users)} verified users")
    except Exception as e:
        logger.error(f"Error loading verified users: {e}")
        verified_users = {}

def save_verified_users():
    try:
        with open(VERIFIED_USERS_FILE, 'w') as f:
            json.dump(verified_users, f)
        logger.info("Saved verified users to file")
    except Exception as e:
        logger.error(f"Error saving verified users: {e}")

async def initialize_twitch():
    try:
        logger.info("Attempting Twitch authentication...")
        twitch_instance = await Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
        await twitch_instance.authenticate_app([])
        logger.info("Twitch API authenticated successfully")
        return twitch_instance
    except Exception as e:
        logger.error(f"Failed to initialize Twitch API: {str(e)}")
        logger.error(traceback.format_exc())
        return None

async def get_channel_id(channel_name):
    try:
        users = await twitch.get_users(logins=[channel_name])
        async for user in users:
            if user.login.lower() == channel_name.lower():
                return user.id
        return None
    except Exception as e:
        logger.error(f"Error getting channel ID: {e}")
        return None

async def get_vips(channel_id):
    vips = []
    try:
        vips_data = await twitch.get_channel_vips(channel_id)
        async for vip in vips_data:
            vips.append(vip.user_login.lower())
        return vips
    except Exception as e:
        logger.error(f"Error getting VIPs: {e}")
        return []

async def get_subscribers(channel_id):
    subscribers = []
    try:
        subs_data = await twitch.get_channel_subscribers(channel_id)
        async for sub in subs_data:
            subscribers.append(sub.user_login.lower())
        return subscribers
    except Exception as e:
        logger.error(f"Error getting subscribers: {e}")
        return []

@tasks.loop(hours=24)
async def sync_roles_task():
    try:
        logger.info("Starting role sync...")
        global twitch
        if twitch is None:
            twitch = await initialize_twitch()
            if twitch is None:
                return

        guild = bot.get_guild(DISCORD_GUILD_ID)
        if not guild:
            logger.error(f"Could not find guild with ID {DISCORD_GUILD_ID}")
            return

        vip_role = guild.get_role(DISCORD_VIP_ROLE_ID)
        if not vip_role:
            logger.error(f"Could not find VIP role")
            return

        sub_role = None
        if DISCORD_SUB_ROLE_ID:
            sub_role = guild.get_role(DISCORD_SUB_ROLE_ID)
            if not sub_role:
                logger.error(f"Could not find Subscriber role")

        channel_id = await get_channel_id(TWITCH_CHANNEL_NAME)
        if not channel_id:
            return

        vips = await get_vips(channel_id)
        subscribers = await get_subscribers(channel_id) if sub_role else []
        
        for discord_id, twitch_username in verified_users.items():
            try:
                member = await guild.fetch_member(int(discord_id))
                if not member:
                    continue

                # Handle VIP role
                is_vip = twitch_username.lower() in vips
                has_vip = vip_role in member.roles

                if is_vip and not has_vip:
                    await member.add_roles(vip_role)
                    logger.info(f"Added VIP role to {member.name}")
                elif not is_vip and has_vip:
                    await member.remove_roles(vip_role)
                    logger.info(f"Removed VIP role from {member.name}")

                # Handle Subscriber role if configured
                if sub_role:
                    is_sub = twitch_username.lower() in subscribers
                    has_sub = sub_role in member.roles

                    if is_sub and not has_sub:
                        await member.add_roles(sub_role)
                        logger.info(f"Added Subscriber role to {member.name}")
                    elif not is_sub and has_sub:
                        await member.remove_roles(sub_role)
                        logger.info(f"Removed Subscriber role from {member.name}")

            except Exception as e:
                logger.error(f"Error processing member {discord_id}: {e}")

    except Exception as e:
        logger.error(f"Error in sync_roles_task: {e}")
        logger.error(traceback.format_exc())

@bot.event
async def on_ready():
    global twitch
    logger.info(f"Bot connected as {bot.user.name}")
    load_verified_users()
    twitch = await initialize_twitch()
    if twitch:
        sync_roles_task.start()
    else:
        logger.error("Failed to initialize Twitch API on startup")

@bot.command(name='link')
async def link_account(ctx, twitch_username: str = None):
    if not twitch_username:
        await ctx.send("❌ Prosím zadej svoje Twitch uživatelské jméno: `!link <twitch_username>`")
        return

    twitch_username = twitch_username.lower()
    discord_id = str(ctx.author.id)
    
    verified_users[discord_id] = twitch_username
    save_verified_users()
    
    await ctx.send(f"✅ Tvůj Discord účet a tvůj Twitch účet byl úspěšně propojen: {twitch_username}\nKontroluji status rolí\n!check pro kontrolu statusu")
    await sync_roles_task()

@bot.command(name='unlink')
async def unlink_account(ctx):
    discord_id = str(ctx.author.id)
    if discord_id in verified_users:
        del verified_users[discord_id]
        save_verified_users()
        await ctx.send("✅ Tvůj účet byl úspešně odpojen.")
        await sync_roles_task()
    else:
        await ctx.send("❌ Tvůj Discord účet není propojen s žádným Twitch účtem.\nPoužij `!link <twitch_username>` pro propojení účtů.")

@bot.command(name='check')
async def check_status(ctx):
    discord_id = str(ctx.author.id)
    
    if discord_id not in verified_users:
        await ctx.send("❌ Tvůj Discord účet není propojen s žádným Twitch účtem.\nPoužij `!link <twitch_username>` pro propojení účtů.")
        return

    twitch_username = verified_users[discord_id]
    await ctx.send(f"✅ Tvůj Discord účet je propojen s tvým Twitch účtem: {twitch_username}")
    
    channel_id = await get_channel_id(TWITCH_CHANNEL_NAME)
    if channel_id:
        vips = await get_vips(channel_id)
        if twitch_username.lower() in vips:
            await ctx.send(f"✅ Máš VIP na kanále {TWITCH_CHANNEL_NAME}")
        else:
            await ctx.send(f"❌ Nemáš VIP na kanále {TWITCH_CHANNEL_NAME}")
        
        if DISCORD_SUB_ROLE_ID:
            subscribers = await get_subscribers(channel_id)
            if twitch_username.lower() in subscribers:
                await ctx.send(f"✅ Máš SUB na kanále {TWITCH_CHANNEL_NAME}")
            else:
                await ctx.send(f"❌ Nemáš SUB na kanále {TWITCH_CHANNEL_NAME}")
    
    guild = ctx.guild
    vip_role = guild.get_role(DISCORD_VIP_ROLE_ID)
    if vip_role in ctx.author.roles:
        await ctx.send("✅ Máš VIP roli na Discordu")
    else:
        await ctx.send("❌ Nemáš VIP roli na Discordu")
    
    if DISCORD_SUB_ROLE_ID:
        sub_role = guild.get_role(DISCORD_SUB_ROLE_ID)
        if sub_role and sub_role in ctx.author.roles:
            await ctx.send("✅ Máš SUB roli na Discordu")
        else:
            await ctx.send("❌ Nemáš SUB roli na Discordu")

@bot.command(name='forcesync')
@commands.has_permissions(administrator=True)
async def force_sync(ctx):
    await ctx.send("🔄 Zahajuji synchronizaci...")
    await sync_roles_task()
    await ctx.send("✅ Synchronizace dokončena!")

@sync_roles_task.before_loop
async def before_sync_roles():
    await bot.wait_until_ready()
    logger.info("Role sync task is ready to start")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
