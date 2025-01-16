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

# Rest of your code remains the same...
