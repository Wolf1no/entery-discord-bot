import discord
from discord.ext import commands, tasks
from twitchAPI.twitch import Twitch
import asyncio
import os
import logging
from typing import Optional

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logs
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

# Initialize Discord bot with all necessary intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variable to store Twitch instance
twitch = None

async def initialize_twitch():
    global twitch
    try:
        logger.info("Attempting Twitch authentication...")
        twitch_instance = await Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
        
        # Authenticate without specifying scopes initially
        await twitch_instance.authenticate_app([])
        
        # Set authentication scopes after initial auth
        # Note: channel:read:vips scope is handled automatically by the API
        logger.info("Twitch API authenticated successfully")
        return twitch_instance
        
    except Exception as e:
        logger.error(f"Failed to initialize Twitch API: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())  # This will show the full error trace
        return None

async def get_twitch_connection(member: discord.Member) -> Optional[str]:
    """Get Twitch username from member's connections."""
    try:
        async for connection in member.fetch_connections():
            if connection.type == 'twitch':
                return connection.name.lower()
    except discord.Forbidden:
        logger.error(f"Cannot access connections for {member.name}")
    except Exception as e:
        logger.error(f"Error fetching connections for {member.name}: {e}")
    return None

@bot.command(name='checkconnection')
async def check_connection(ctx):
    """Command to check user's Twitch connection and VIP status."""
    try:
        # Check if twitch API is initialized
        global twitch
        if twitch is None:
            twitch = await initialize_twitch()
            if twitch is None:
                await ctx.send("❌ Bot cannot connect to Twitch API!")
                return

        # Get user's Twitch connection
        twitch_name = await get_twitch_connection(ctx.author)
        if not twitch_name:
            await ctx.send("❌ No Twitch account connected to your Discord! Please connect your Twitch account in Discord User Settings > Connections")
            return

        await ctx.send(f"✅ Found your Twitch connection: {twitch_name}")

        # Check if channel exists
        channel_id = await get_channel_id(TWITCH_CHANNEL_NAME)
        if not channel_id:
            await ctx.send(f"❌ Could not find Twitch channel: {TWITCH_CHANNEL_NAME}")
            return

        # Get VIPs
        vips = await get_vips(channel_id)
        is_vip = twitch_name in vips

        # Check VIP status
        if is_vip:
            await ctx.send(f"✅ You are a VIP in channel {TWITCH_CHANNEL_NAME}")
        else:
            await ctx.send(f"❌ You are not a VIP in channel {TWITCH_CHANNEL_NAME}")

        # Check Discord role
        guild = ctx.guild
        vip_role = guild.get_role(DISCORD_VIP_ROLE_ID)
        has_role = vip_role in ctx.author.roles

        if has_role:
            await ctx.send("✅ You have the VIP role in Discord")
        else:
            await ctx.send("❌ You don't have the VIP role in Discord")

    except Exception as e:
        logger.error(f"Error in check_connection: {e}")
        await ctx.send(f"❌ An error occurred: {str(e)}")

@bot.command(name='forcesync')
@commands.has_permissions(administrator=True)
async def force_sync(ctx):
    """Force a sync of VIP roles (admin only)."""
    await ctx.send("🔄 Forcing VIP role sync...")
    await sync_vip_roles()
    await ctx.send("✅ Sync complete!")

async def get_channel_id(twitch_channel_name):
    try:
        # Handle the response correctly
        response = await twitch.get_users(logins=[twitch_channel_name])
        logger.debug(f"get_users response: {response}")
        
        # Check if we have data in the response
        if hasattr(response, 'data') and response.data:
            return response.data[0].id
        else:
            # If response is an async generator, handle it differently
            async for user in response:
                if user.get('login', '').lower() == twitch_channel_name.lower():
                    return user.get('id')
                
        logger.error(f"Channel {twitch_channel_name} not found")
        return None
    except Exception as e:
        logger.error(f"Error getting channel ID: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

async def get_vips(channel_id):
    vips = []
    try:
        logger.info(f"Fetching VIPs for channel ID: {channel_id}")
        
        # Handle the VIP response
        response = await twitch.get_channel_vips(channel_id)
        
        # If response is an async generator
        if hasattr(response, '__aiter__'):
            async for vip in response:
                if isinstance(vip, dict) and 'user_login' in vip:
                    vips.append(vip['user_login'].lower())
                elif hasattr(vip, 'user_login'):
                    vips.append(vip.user_login.lower())
        # If response is a direct object
        elif hasattr(response, 'data'):
            for vip in response.data:
                if isinstance(vip, dict) and 'user_login' in vip:
                    vips.append(vip['user_login'].lower())
                elif hasattr(vip, 'user_login'):
                    vips.append(vip.user_login.lower())
                    
        logger.info(f"Retrieved VIPs: {vips}")
        return vips
    except Exception as e:
        logger.error(f"Error getting VIPs: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

@tasks.loop(minutes=5)
async def sync_vip_roles():
    try:
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

        # Add debug logging for channel name
        logger.info(f"Looking up channel ID for: {TWITCH_CHANNEL_NAME}")
        channel_id = await get_channel_id(TWITCH_CHANNEL_NAME)
        
        if not channel_id:
            logger.error("Could not get channel ID")
            return

        logger.info(f"Successfully found channel ID: {channel_id}")
        vips = await get_vips(channel_id)
        logger.info(f"Retrieved {len(vips)} VIPs from Twitch")

        for member in guild.members:
            twitch_name = await get_twitch_connection(member)
            if twitch_name:
                logger.info(f"Processing {member.name} with Twitch: {twitch_name}")
                
                if twitch_name in vips and vip_role not in member.roles:
                    await member.add_roles(vip_role)
                    logger.info(f"Added VIP role to {member.name}")
                elif twitch_name not in vips and vip_role in member.roles:
                    await member.remove_roles(vip_role)
                    logger.info(f"Removed VIP role from {member.name}")

    except Exception as e:
        logger.error(f"Error in sync_vip_roles: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
