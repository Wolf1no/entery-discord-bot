import discord
from discord.ext import commands, tasks
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.types import AuthScope
import asyncio
import os
import json
import logging
import traceback
import random
import string
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

# Optional environment variables for tokens
TWITCH_ACCESS_TOKEN = os.environ.get('TWITCH_ACCESS_TOKEN')
TWITCH_REFRESH_TOKEN = os.environ.get('TWITCH_REFRESH_TOKEN')

# File paths
VERIFIED_USERS_FILE = 'verified_users.json'
TOKENS_FILE = 'twitch_tokens.json'

# Initialize Discord bot with all necessary intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
twitch = None
verification_codes: Dict[str, dict] = {}  # Store temporary verification codes
verified_users: Dict[str, str] = {}  # Store Discord ID -> Twitch username mappings

async def save_tokens(token: str, refresh_token: str):
    """Save authentication tokens to a file"""
    try:
        with open(TOKENS_FILE, 'w') as f:
            json.dump({
                'token': token,
                'refresh_token': refresh_token
            }, f)
        logger.info("Successfully saved authentication tokens")
    except Exception as e:
        logger.error(f"Error saving tokens: {e}")

async def load_tokens() -> tuple[str, str] | None:
    """Load authentication tokens from file or environment"""
    # First try environment variables
    if TWITCH_ACCESS_TOKEN and TWITCH_REFRESH_TOKEN:
        logger.info("Using tokens from environment variables")
        return TWITCH_ACCESS_TOKEN, TWITCH_REFRESH_TOKEN
    
    # Then try file
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, 'r') as f:
                data = json.load(f)
                logger.info("Successfully loaded tokens from file")
                return data['token'], data['refresh_token']
    except Exception as e:
        logger.error(f"Error loading tokens: {e}")
    return None

def generate_verification_code() -> str:
    """Generate a random 6-character verification code"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def load_verified_users():
    """Load verified users from file"""
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
    """Save verified users to file"""
    try:
        with open(VERIFIED_USERS_FILE, 'w') as f:
            json.dump(verified_users, f)
        logger.info("Saved verified users to file")
    except Exception as e:
        logger.error(f"Error saving verified users: {e}")

async def initialize_twitch():
    """Initialize Twitch API with user authentication"""
    global twitch
    try:
        logger.info("Attempting Twitch authentication...")
        twitch_instance = await Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
        
        target_scope = [AuthScope.CHANNEL_READ_VIPS]
        
        # Try to load existing tokens
        tokens = await load_tokens()
        if tokens:
            token, refresh_token = tokens
            try:
                await twitch_instance.set_user_authentication(token, target_scope, refresh_token)
                logger.info("Successfully authenticated using saved tokens")
                return twitch_instance
            except Exception as e:
                logger.warning(f"Failed to use saved tokens: {e}")
        
        # If no tokens or they failed, do browser authentication
        auth = UserAuthenticator(twitch_instance, target_scope, force_verify=False)
        try:
            token, refresh_token = await auth.authenticate()
            await save_tokens(token, refresh_token)
            await twitch_instance.set_user_authentication(token, target_scope, refresh_token)
            logger.info("Twitch API authenticated successfully with user access")
            return twitch_instance
        except Exception as e:
            logger.error(f"User authentication failed: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to initialize Twitch API: {str(e)}")
        logger.error(traceback.format_exc())
        return None

async def get_channel_id(channel_name):
    """Get Twitch channel ID from channel name"""
    try:
        users_generator = await twitch.get_users(logins=[channel_name])
        
        for user in users_generator:
            if user.login.lower() == channel_name.lower():
                logger.info(f"Found channel ID for {channel_name}: {user.id}")
                return user.id
            
        logger.error(f"Channel {channel_name} not found")
        return None
    except Exception as e:
        logger.error(f"Error getting channel ID: {e}")
        logger.error(traceback.format_exc())
        return None

async def get_vips(channel_id):
    """Get list of VIPs for a channel"""
    vips = []
    try:
        logger.info(f"Fetching VIPs for channel ID: {channel_id}")
        vips_generator = await twitch.get_vips(broadcaster_id=channel_id)
        
        for vip in vips_generator:
            vips.append(vip.user_login.lower())
            logger.debug(f"Found VIP: {vip.user_login}")
            
        logger.info(f"Retrieved {len(vips)} VIPs: {vips}")
        return vips
    except Exception as e:
        logger.error(f"Error getting VIPs: {e}")
        logger.error(traceback.format_exc())
        return []

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    global twitch
    logger.info(f"Bot connected as {bot.user.name}")
    load_verified_users()
    twitch = await initialize_twitch()
    if twitch:
        logger.info("Starting VIP role sync task")
        sync_vip_roles.start()
    else:
        logger.error("Failed to initialize Twitch API on startup")

@bot.command(name='link')
async def link_account(ctx, twitch_username: str = None):
    """Link Discord account to Twitch account"""
    if not twitch_username:
        await ctx.send("❌ Please provide your Twitch username: `!link <twitch_username>`")
        return

    twitch_username = twitch_username.lower()
    verification_code = generate_verification_code()
    
    verification_codes[verification_code] = {
        'discord_id': str(ctx.author.id),
        'twitch_username': twitch_username,
        'timestamp': ctx.message.created_at.timestamp()
    }

    await ctx.send(
        f"✅ Verification code generated! To verify your Twitch account:\n\n"
        f"1. Go to twitch.tv/{TWITCH_CHANNEL_NAME}\n"
        f"2. Type this in chat: `!verify {verification_code}`\n\n"
        "The code will expire in 5 minutes. Use `!check` to see your current link status."
    )

@bot.command(name='verify')
async def verify_code(ctx, code: str = None):
    """Verify a Twitch account with the provided code"""
    if code and code.upper() in verification_codes:
        data = verification_codes[code.upper()]
        if ctx.author.name.lower() == data['twitch_username'].lower():
            verified_users[data['discord_id']] = data['twitch_username']
            save_verified_users()
            await ctx.send(f"✅ Successfully verified {ctx.author.name}")
            del verification_codes[code.upper()]
            
            # Force a sync to update roles
            await sync_vip_roles()
        else:
            await ctx.send("❌ This code was generated for a different Twitch account.")
    else:
        await ctx.send("❌ Invalid or expired verification code.")

@bot.command(name='unlink')
async def unlink_account(ctx):
    """Unlink Discord account from Twitch account"""
    discord_id = str(ctx.author.id)
    if discord_id in verified_users:
        del verified_users[discord_id]
        save_verified_users()
        await ctx.send("✅ Successfully unlinked your account.")
        
        # Force a sync to update roles
        await sync_vip_roles()
    else:
        await ctx.send("❌ Your account is not linked to any Twitch account.")

@bot.command(name='check')
async def check_status(ctx):
    """Check current link status and VIP status"""
    discord_id = str(ctx.author.id)
    
    if discord_id not in verified_users:
        await ctx.send("❌ Your Discord account is not linked to any Twitch account.\nUse `!link <twitch_username>` to link your account.")
        return

    twitch_username = verified_users[discord_id]
    await ctx.send(f"✅ Your Discord account is linked to Twitch account: {twitch_username}")
    
    # Check VIP status
    channel_id = await get_channel_id(TWITCH_CHANNEL_NAME)
    if channel_id:
        vips = await get_vips(channel_id)
        if twitch_username.lower() in vips:
            await ctx.send(f"✅ You are a VIP in channel {TWITCH_CHANNEL_NAME}")
        else:
            await ctx.send(f"❌ You are not a VIP in channel {TWITCH_CHANNEL_NAME}")
    
    # Check Discord role
    guild = ctx.guild
    vip_role = guild.get_role(DISCORD_VIP_ROLE_ID)
    if vip_role in ctx.author.roles:
        await ctx.send("✅ You have the VIP role in Discord")
    else:
        await ctx.send("❌ You don't have the VIP role in Discord")

@bot.command(name='forcesync')
@commands.has_permissions(administrator=True)
async def force_sync(ctx):
    """Force a sync of VIP roles (admin only)"""
    await ctx.send("🔄 Forcing VIP role sync...")
    await sync_vip_roles()
    await ctx.send("✅ Sync complete!")

@tasks.loop(hours=24)
async def sync_vip_roles():
    """Sync VIP roles between Twitch and Discord daily"""
    try:
        logger.info("Starting VIP role sync...")
        global twitch
        if twitch is None:
            logger.warning("Attempting to reinitialize Twitch API...")
            twitch = await initialize_twitch()
            if twitch is None:
                logger.error("Failed to initialize Twitch API")
                return

        guild = bot.get_guild(DISCORD_GUILD_ID)
        if not guild:
            logger.error(f"Could not find guild with ID {DISCORD_GUILD_ID}")
            return

        vip_role = guild.get_role(DISCORD_VIP_ROLE_ID)
        if not vip_role:
            logger.error(f"Could not find VIP role with ID {DISCORD_VIP_ROLE_ID}")
            return

        channel_id = await get_channel_id(TWITCH_CHANNEL_NAME)
        if not channel_id:
            logger.error("Could not get channel ID")
            return

        vips = await get_vips(channel_id)
        logger.info(f"Retrieved {len(vips)} VIPs")

        sync_count = 0
        for discord_id, twitch_username in verified_users.items():
            member = await guild.fetch_member(int(discord_id))
            if not member:
                continue

            is_vip = twitch_username.lower() in vips
            has_role = vip_role in member.roles

            if is_vip and not has_role:
                await member.add_roles(vip_role)
                sync_count += 1
                logger.info(f"Added VIP role to {member.name}")
            elif not is_vip and has_role:
                await member.remove_roles(vip_role)
                sync_count += 1
                logger.info(f"Removed VIP role from {member.name}")

        logger.info(f"Sync completed. Made {sync_count} role changes.")

    except Exception as e:
        logger.error(f"Error in sync_vip_roles: {e}")
        logger.error(traceback.format_exc())

@sync_vip_roles.before_loop
async def before_sync_vip_roles():
    """Wait until the bot is ready before starting the sync loop"""
    await bot.wait_until_ready()
    logger.info("VIP role sync task is ready to start")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
