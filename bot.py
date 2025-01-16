import discord
from discord.ext import commands, tasks
from twitchAPI.twitch import Twitch
import asyncio
import os
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
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

# Initialize Discord bot
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variable to store Twitch instance
twitch = None

async def initialize_twitch():
    global twitch
    try:
        logger.info("Attempting Twitch authentication...")
        twitch_instance = await Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
        
        # Explicitly specify the required scopes for VIP access
        required_scopes = [
            'channel:read:vips',
            'moderator:read:chatters'
        ]
        
        logger.info(f"Authenticating with scopes: {required_scopes}")
        await twitch_instance.authenticate_app(required_scopes)
        
        # Verify authentication
        logger.info("Testing API access...")
        try:
            users = await twitch_instance.get_users(logins=[TWITCH_CHANNEL_NAME])
            logger.info("API access test successful")
        except Exception as e:
            logger.error(f"API access test failed: {e}")
            return None
            
        logger.info("Twitch API authenticated successfully")
        return twitch_instance
    except Exception as e:
        logger.error(f"Failed to initialize Twitch API: {str(e)}")
        logger.error(f"Make sure your application has the required scopes enabled")
        return None

async def get_channel_id(channel_name):
    global twitch
    try:
        if twitch is None:
            logger.error("Twitch API not initialized")
            return None
        
        users = await twitch.get_users(logins=[channel_name])
        if not users['data']:
            logger.error(f"Channel {channel_name} not found")
            return None
        return users['data'][0]['id']
    except Exception as e:
        logger.error(f"Error getting channel ID: {e}")
        return None

async def get_vips(channel_id):
    global twitch
    vips = []
    try:
        if twitch is None:
            logger.error("Twitch API not initialized")
            return []
            
        async for vip in twitch.get_channel_vips(channel_id):
            vips.append(vip['user_login'].lower())
        return vips
    except Exception as e:
        logger.error(f"Error getting VIPs: {e}")
        return []

@tasks.loop(minutes=5)
async def sync_vip_roles():
    global twitch
    try:
        if twitch is None:
            logger.warning("Attempting to reinitialize Twitch API...")
            twitch = await initialize_twitch()
            if twitch is None:
                logger.error("Failed to reinitialize Twitch API")
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
        if channel_id is None:
            return
            
        twitch_vips = await get_vips(channel_id)
        
        for member in guild.members:
            if len(member.activities) > 0:
                for activity in member.activities:
                    if isinstance(activity, discord.Streaming):
                        twitch_name = activity.twitch_name.lower() if activity.twitch_name else None
                        
                        if twitch_name and twitch_name in twitch_vips and vip_role not in member.roles:
                            await member.add_roles(vip_role)
                            logger.info(f"Added VIP role to {member.name}")
                        
                        elif twitch_name and twitch_name not in twitch_vips and vip_role in member.roles:
                            await member.remove_roles(vip_role)
                            logger.info(f"Removed VIP role from {member.name}")
    except Exception as e:
        logger.error(f"Error in sync_vip_roles: {e}")

@bot.event
async def on_ready():
    global twitch
    logger.info(f'Bot is ready: {bot.user.name}')
    # Initialize Twitch API when bot starts
    twitch = await initialize_twitch()
    if twitch is None:
        logger.error("Failed to initialize Twitch API during startup")
    else:
        sync_vip_roles.start()

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
