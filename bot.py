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

# Debug logging for credentials (remove in production)
logger.info(f"Checking for required environment variables...")
if not os.getenv("TWITCH_CLIENT_ID"):
    logger.error("TWITCH_CLIENT_ID is missing!")
if not os.getenv("TWITCH_CLIENT_SECRET"):
    logger.error("TWITCH_CLIENT_SECRET is missing!")

# Configuration from GitHub Secrets
TWITCH_CLIENT_ID = os.environ['TWITCH_CLIENT_ID']
TWITCH_CLIENT_SECRET = os.environ['TWITCH_CLIENT_SECRET']
DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
TWITCH_CHANNEL_NAME = os.environ['TWITCH_CHANNEL_NAME']
DISCORD_GUILD_ID = int(os.environ['DISCORD_GUILD_ID'])
DISCORD_VIP_ROLE_ID = int(os.environ['DISCORD_VIP_ROLE_ID'])

# Validate essential credentials
if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
    raise ValueError("Missing Twitch Client ID or Client Secret!")

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
        
        # Authenticate using app credentials
        await twitch_instance.authenticate_app(['channel:read:vips'])
        
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
        logger.error("Make sure your application has the required scopes enabled")
        return None
        
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
        logger.info(f"Found VIPs: {twitch_vips}")
        
        for member in guild.members:
            try:
                # Fetch the member with their connection data
                full_member = await guild.fetch_member(member.id)
                
                # Check if member has Twitch connected
                twitch_connection = None
                async for connection in full_member.fetch_connections():
                    if connection.type == 'twitch':
                        twitch_connection = connection
                        break
                
                if twitch_connection:
                    twitch_name = twitch_connection.name.lower()
                    logger.info(f"Found Twitch connection for {member.name}: {twitch_name}")
                    
                    if twitch_name in twitch_vips and vip_role not in member.roles:
                        await member.add_roles(vip_role)
                        logger.info(f"Added VIP role to {member.name} (Twitch: {twitch_name})")
                    elif twitch_name not in twitch_vips and vip_role in member.roles:
                        await member.remove_roles(vip_role)
                        logger.info(f"Removed VIP role from {member.name} (Twitch: {twitch_name})")
                else:
                    logger.debug(f"No Twitch connection found for {member.name}")
                    
            except discord.Forbidden:
                logger.error(f"Missing permissions to fetch connections for {member.name}")
            except Exception as e:
                logger.error(f"Error processing member {member.name}: {e}")
                
    except Exception as e:
        logger.error(f"Error in sync_vip_roles: {e}")

# We need to add the connections intent
intents = discord.Intents.default()
intents.members = True
intents.presences = True  # Add presences intent
bot = commands.Bot(command_prefix='!', intents=intents)
# Rest of your code remains the same...
