import discord
from discord.ext import commands, tasks
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope
import asyncio
import os
import json
import logging
import traceback
from typing import Optional, Dict
from datetime import datetime
from twitch_auth import TwitchAuthManager

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from GitHub Secrets
TWITCH_CLIENT_ID = os.environ['TWITCH_CLIENT_ID']
TWITCH_CLIENT_SECRET = os.environ['TWITCH_CLIENT_SECRET']
DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
TWITCH_CHANNEL_NAME = os.environ['TWITCH_CHANNEL_NAME']
DISCORD_GUILD_ID = int(os.environ['DISCORD_GUILD_ID'])
DISCORD_VIP_ROLE_ID = int(os.environ['DISCORD_VIP_ROLE_ID'])
DISCORD_SUB_ROLE_ID = int(os.environ.get('DISCORD_SUB_ROLE_ID', 0))
DISCORD_MOD_CHANNEL_ID = int(os.environ.get('DISCORD_MOD_CHANNEL_ID', 0))

# File paths
VERIFIED_USERS_FILE = 'verified_users.json'
TOKEN_FILE = 'twitch_tokens.json'

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
twitch = None
auth_manager = None
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
    global auth_manager, twitch
    try:
        logger.info("Attempting Twitch authentication...")
        auth_manager = TwitchAuthManager(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_CHANNEL_NAME)
        twitch_instance = await auth_manager.initialize()
        
        if twitch_instance:
            # Make sure we have valid user authentication
            if hasattr(twitch_instance, 'has_user_auth') and twitch_instance.has_user_auth:
                logger.info("Twitch API authenticated successfully with user auth")
                twitch = twitch_instance
                return twitch_instance
            else:
                logger.warning("Twitch API initialized but missing user authentication")
                if DISCORD_MOD_CHANNEL_ID:
                    channel = bot.get_channel(DISCORD_MOD_CHANNEL_ID)
                    if channel:
                        await channel.send("⚠️ Je potřeba obnovit Twitch autorizaci! Použij příkaz `!setupauth`")
                return None
        else:
            logger.error("Failed to initialize Twitch API")
            return None
            
    except Exception as e:
        logger.error(f"Failed to initialize Twitch API: {e}")
        logger.error(traceback.format_exc())
        return None

async def get_channel_id(channel_name):
    try:
        logger.info(f"Getting channel ID for: {channel_name}")
        users = twitch.get_users(logins=[channel_name])
        
        async for user in users:
            if user.login.lower() == channel_name.lower():
                logger.info(f"Found channel ID: {user.id} for user: {user.login}")
                return user.id
        
        logger.warning(f"No user found for channel name: {channel_name}")
        return None
    except Exception as e:
        logger.error(f"Error getting channel ID: {e}", exc_info=True)
        return None

async def get_vips(channel_id):
    vips = []
    try:
        logger.info(f"Getting VIPs for channel ID: {channel_id}")
        
        # Make sure we have valid authentication
        if not twitch or not hasattr(twitch, 'has_user_auth') or not twitch.has_user_auth:
            if DISCORD_MOD_CHANNEL_ID:
                channel = bot.get_channel(DISCORD_MOD_CHANNEL_ID)
                if channel:
                    await channel.send("⚠️ Je potřeba obnovit Twitch autorizaci! Použij příkaz `!setupauth`")
            return []
        
        try:
            # Get VIPs with proper await
            vips_data = await twitch.get_vips(broadcaster_id=channel_id)
            if isinstance(vips_data, list):
                for vip in vips_data:
                    vips.append(vip.user_login.lower())
            logger.info(f"Found {len(vips)} VIPs")
        except Exception as api_error:
            logger.error(f"API Error getting VIPs: {api_error}")
            if "require user authentication" in str(api_error):
                if DISCORD_MOD_CHANNEL_ID:
                    channel = bot.get_channel(DISCORD_MOD_CHANNEL_ID)
                    if channel:
                        await channel.send("⚠️ Je potřeba obnovit Twitch autorizaci! Použij příkaz `!setupauth`")
        
        return vips
        
    except Exception as e:
        logger.error(f"Error getting VIPs: {e}", exc_info=True)
        return []

async def get_subscribers(channel_id):
    subscribers = []
    try:
        logger.info(f"Getting subscribers for channel ID: {channel_id}")
        
        # Make sure we have valid authentication
        if not twitch or not hasattr(twitch, 'has_user_auth') or not twitch.has_user_auth:
            if DISCORD_MOD_CHANNEL_ID:
                channel = bot.get_channel(DISCORD_MOD_CHANNEL_ID)
                if channel:
                    await channel.send("⚠️ Je potřeba obnovit Twitch autorizaci! Použij příkaz `!setupauth`")
            return []
        
        try:
            # Get subscribers with proper await
            subs_data = await twitch.get_broadcaster_subscriptions(broadcaster_id=channel_id)
            if isinstance(subs_data, list):
                for sub in subs_data:
                    subscribers.append(sub.user_login.lower())
            logger.info(f"Found {len(subscribers)} subscribers")
        except Exception as api_error:
            logger.error(f"API Error getting subscribers: {api_error}")
            if "require user authentication" in str(api_error):
                if DISCORD_MOD_CHANNEL_ID:
                    channel = bot.get_channel(DISCORD_MOD_CHANNEL_ID)
                    if channel:
                        await channel.send("⚠️ Je potřeba obnovit Twitch autorizaci! Použij příkaz `!setupauth`")
        
        return subscribers
        
    except Exception as e:
        logger.error(f"Error getting subscribers: {e}", exc_info=True)
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
        logger.info("Role sync task started")
    else:
        logger.error("Failed to initialize Twitch API on startup")

@bot.command(name='setupauth')
@commands.has_permissions(administrator=True)
async def setup_auth(ctx):
    """Generate Twitch authentication URL"""
    try:
        global auth_manager
        if not auth_manager:
            auth_manager = TwitchAuthManager(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_CHANNEL_NAME)
            await auth_manager.initialize()
        
        # Send initial status message
        initial_embed = discord.Embed(
            title="🔄 Inicializace Twitch autentizace",
            description="```diff\n+ Generuji bezpečný autentizační odkaz...\n```",
            color=0x9147ff  # Twitch purple
        )
        setup_msg = await ctx.send(embed=initial_embed)
        
        # Get authentication URL
        auth_url = await auth_manager.generate_auth_url()
        if auth_url:
            auth_embed = discord.Embed(
                title="🔐 Nastavení Twitch autentizace",
                description=(
                    "**Postup autentizace:**\n\n"
                    "**`1️⃣`** Klikni na autentizační odkaz níže\n"
                    "**`2️⃣`** Přihlaš se na Twitch a povol přístup\n"
                    "**`3️⃣`** Po přesměrování na localhost zkopíruj **celou** URL\n"
                    "**`4️⃣`** Použij příkaz:\n"
                    "```\n!completeauth <zkopírovaná-url>\n```\n"
                    f"{auth_url}"
                ),
                color=0x9147ff
            )
            await setup_msg.edit(embed=auth_embed)
        else:
            error_embed = discord.Embed(
                title="❌ Chyba při generování",
                description=(
                    "```diff\n- Nepodařilo se vygenerovat autentizační odkaz\n```\n"
                    "**Možné příčiny:**\n"
                    "• Problém s připojením k Twitch API\n"
                    "• Neplatné přihlašovací údaje\n"
                    "• Dočasná nedostupnost služby"
                ),
                color=discord.Color.red()
            )
            await setup_msg.edit(embed=error_embed)
            
    except Exception as e:
        logger.error(f"Error in setup_auth: {e}")
        await ctx.send(
            embed=discord.Embed(
                title="⚠️ Systémová chyba",
                description="```diff\n- Nastala neočekávaná chyba\n```\nProsím, kontaktujte administrátora.",
                color=discord.Color.red()
            )
        )

@bot.command(name='completeauth')
@commands.has_permissions(administrator=True)
async def complete_auth(ctx, auth_code: str):
    """Complete the authentication process"""
    try:
        await ctx.message.delete()  # Delete the message containing the auth code
        
        # Send initial status
        status_embed = discord.Embed(
            title="🔄 Zpracování autentizace",
            description="```yaml\nProbíhá ověření a nastavení...\n```",
            color=0x9147ff
        )
        status_msg = await ctx.send(embed=status_embed)
        
        global auth_manager, twitch
        if not auth_manager:
            auth_manager = TwitchAuthManager(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_CHANNEL_NAME)
            await auth_manager.initialize()
            
        if await auth_manager.set_user_auth(auth_code):
            twitch = auth_manager.twitch
            success_embed = discord.Embed(
                title="✅ Autentizace úspěšná",
                description=(
                    "```diff\n+ Twitch autentizace byla úspěšně dokončena!\n```\n"
                    "**Provedené akce:**\n"
                    "• Ověření autentizačního kódu\n"
                    "• Nastavení Twitch API\n"
                    "• Aktivace synchronizace rolí"
                ),
                color=discord.Color.green()
            )
            success_embed.set_footer(text=f"Dokončeno • {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
            await status_msg.edit(embed=success_embed)
        else:
            error_embed = discord.Embed(
                title="❌ Chyba autentizace",
                description=(
                    "```diff\n- Nepodařilo se dokončit autentizaci\n```\n"
                    "**Možné příčiny:**\n"
                    "• Neplatný nebo expirovaný kód\n"
                    "• Chyba při komunikaci s Twitch API\n"
                    "• Nedostatečná oprávnění\n\n"
                    "Prosím, vygenerujte nový autentizační odkaz pomocí `!setupauth`"
                ),
                color=discord.Color.red()
            )
            await status_msg.edit(embed=error_embed)
    except Exception as e:
        logger.error(f"Error in complete_auth: {e}")
        await ctx.send(
            embed=discord.Embed(
                title="⚠️ Chyba při autentizaci",
                description="```diff\n- Nastala neočekávaná chyba při dokončování autentizace\n```",
                color=discord.Color.red()
            )
        )

@bot.command(name='link')
async def link_account(ctx, twitch_username: str = None):
    """Link Discord account with Twitch account"""
    if not twitch_username:
        await ctx.send(
            embed=discord.Embed(
                title="❌ Chybí uživatelské jméno",
                description="```diff\n- Prosím zadej svoje Twitch uživatelské jméno\n```\n**Použití:**\n`!link <twitch_username>`",
                color=discord.Color.red()
            )
        )
        return

    twitch_username = twitch_username.lower()
    discord_id = str(ctx.author.id)
    
    # Send initial status
    status_embed = discord.Embed(
        title="🔄 Probíhá propojení účtů",
        description="```yaml\nUkládám propojení účtů...\n```",
        color=0x9147ff
    )
    status_msg = await ctx.send(embed=status_embed)
    
    try:
        verified_users[discord_id] = twitch_username
        save_verified_users()
        
        success_embed = discord.Embed(
            title="✅ Účty úspěšně propojeny",
            description=(
                f"```diff\n+ Discord účet byl propojen s Twitch účtem\n```\n"
                f"**Twitch účet:** `{twitch_username}`\n"
                f"**Discord účet:** {ctx.author.mention}\n\n"
                "**Další kroky:**\n"
                "• Použij `!check` pro kontrolu statusu rolí\n"
                "• Role se synchronizují automaticky každých 24 hodin\n"
                "• Administrátor může vynutit okamžitou synchronizaci"
            ),
            color=discord.Color.green()
        )
        success_embed.set_footer(text=f"Propojeno • {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        await status_msg.edit(embed=success_embed)
        await sync_roles_task()
        
    except Exception as e:
        logger.error(f"Error in link_account: {e}")
        error_embed = discord.Embed(
            title="❌ Chyba při propojování",
            description="```diff\n- Nastala chyba při propojování účtů\n```",
            color=discord.Color.red()
        )
        await status_msg.edit(embed=error_embed)

@bot.command(name='unlink')
async def unlink_account(ctx):
    """Unlink Discord account from Twitch account"""
    discord_id = str(ctx.author.id)
    
    status_embed = discord.Embed(
        title="🔄 Kontrola propojení",
        description="```yaml\nKontroluji propojení účtů...\n```",
        color=0x9147ff
    )
    status_msg = await ctx.send(embed=status_embed)
    
    try:
        if discord_id in verified_users:
            twitch_username = verified_users[discord_id]
            del verified_users[discord_id]
            save_verified_users()
            
            success_embed = discord.Embed(
                title="✅ Účty odpojeny",
                description=(
                    "```diff\n+ Účty byly úspěšně odpojeny\n```\n"
                    f"**Odpojený Twitch účet:** `{twitch_username}`\n"
                    f"**Discord účet:** {ctx.author.mention}\n\n"
                    "**Info:**\n"
                    "• VIP/SUB role budou odebrány při příští synchronizaci\n"
                    "• Pro opětovné propojení použij `!link <twitch_username>`"
                ),
                color=discord.Color.green()
            )
            success_embed.set_footer(text=f"Odpojeno • {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
            await status_msg.edit(embed=success_embed)
            await sync_roles_task()
        else:
            not_linked_embed = discord.Embed(
                title="❌ Účet není propojen",
                description=(
                    "```diff\n- Tvůj Discord účet není propojen s žádným Twitch účtem\n```\n"
                    "**Jak propojit účty:**\n"
                    "• Použij příkaz `!link <twitch_username>`\n"
                    "• Po propojení použij `!check` pro kontrolu"
                ),
                color=discord.Color.red()
            )
            await status_msg.edit(embed=not_linked_embed)
            
    except Exception as e:
        logger.error(f"Error in unlink_account: {e}")
        error_embed = discord.Embed(
            title="⚠️ Chyba při odpojování",
            description="```diff\n- Nastala neočekávaná chyba při odpojování účtů\n```",
            color=discord.Color.red()
        )
        await status_msg.edit(embed=error_embed)

@bot.command(name='check')
async def check_status(ctx):
    discord_id = str(ctx.author.id)
    
    if discord_id not in verified_users:
        embed = discord.Embed(
            title="❌ Účet není propojen",
            description="Tvůj Discord účet není propojen s žádným Twitch účtem.\nPoužij `!link <twitch_username>` pro propojení účtů.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    twitch_username = verified_users[discord_id]
    embed = discord.Embed(
        title="📊 Status účtu",
        description=f"Discord účet je propojen s Twitch účtem: **{twitch_username}**",
        color=discord.Color.blue()
    )

    # Check Twitch status
    channel_id = await get_channel_id(TWITCH_CHANNEL_NAME)
    if channel_id:
        vips = await get_vips(channel_id)
        is_vip_twitch = twitch_username.lower() in vips
        embed.add_field(
            name="Twitch VIP Status",
            value=f"{'✅' if is_vip_twitch else '❌'} {'Máš' if is_vip_twitch else 'Nemáš'} VIP na kanále {TWITCH_CHANNEL_NAME}",
            inline=False
        )

        if DISCORD_SUB_ROLE_ID:
            subscribers = await get_subscribers(channel_id)
            is_sub_twitch = twitch_username.lower() in subscribers
            embed.add_field(
                name="Twitch SUB Status",
                value=f"{'✅' if is_sub_twitch else '❌'} {'Máš' if is_sub_twitch else 'Nemáš'} SUB na kanále {TWITCH_CHANNEL_NAME}",
                inline=False
            )

    # Check Discord roles
    guild = ctx.guild
    vip_role = guild.get_role(DISCORD_VIP_ROLE_ID)
    has_vip_discord = vip_role in ctx.author.roles
    embed.add_field(
        name="Discord VIP Status",
        value=f"{'✅' if has_vip_discord else '❌'} {'Máš' if has_vip_discord else 'Nemáš'} VIP roli na Discordu",
        inline=False
    )

    if DISCORD_SUB_ROLE_ID:
        sub_role = guild.get_role(DISCORD_SUB_ROLE_ID)
        has_sub_discord = sub_role and sub_role in ctx.author.roles
        embed.add_field(
            name="Discord SUB Status",
            value=f"{'✅' if has_sub_discord else '❌'} {'Máš' if has_sub_discord else 'Nemáš'} SUB roli na Discordu",
            inline=False
        )

    embed.set_footer(text=f"Poslední kontrola: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    await ctx.send(embed=embed)

@bot.command(name='commands')
async def show_commands(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="📋 Dostupné příkazy",
        description="Seznam všech dostupných příkazů:",
        color=discord.Color.blue()
    )
    
    # Basic commands for all users
    basic_commands = [
        "`!link <twitch_username>` - Propojí tvůj Discord účet s Twitch účtem",
        "`!unlink` - Odpojí tvůj Discord účet od Twitch účtu",
        "`!check` - Zkontroluje stav propojení a rolí",
        "`!commands` - Zobrazí tento seznam příkazů"
    ]
    embed.add_field(name="👥 Základní příkazy", value="\n".join(basic_commands), inline=False)
    
    # Admin commands
    if ctx.author.guild_permissions.administrator:
        admin_commands = [
            "`!forcesync` - Vynutí synchronizaci rolí pro všechny propojené účty",
            "`!setupauth` - Vygeneruje autentizační odkaz pro Twitch",
            "`!completeauth <code>` - Dokončí Twitch autentizaci pomocí kódem"
        ]
        embed.add_field(name="⚡ Administrátorské příkazy", value="\n".join(admin_commands), inline=False)
    
    embed.set_footer(text=f"Bot created by Wolf1no")
    await ctx.send(embed=embed)


@bot.command(name='forcesync')
@commands.has_permissions(administrator=True)
async def force_sync(ctx):
    embed = discord.Embed(
        title="🔄 Synchronizace rolí",
        description="Zahajuji synchronizaci...",
        color=discord.Color.blue()
    )
    message = await ctx.send(embed=embed)
    
    try:
        await sync_roles_task()
        embed.description = "✅ Synchronizace dokončena!"
        embed.color = discord.Color.green()
        logger.info("Force sync completed successfully")
    except Exception as e:
        embed.description = f"❌ Chyba při synchronizaci: {str(e)}"
        embed.color = discord.Color.red()
        logger.error(f"Error in force_sync: {e}", exc_info=True)
    
    await message.edit(embed=embed)

@sync_roles_task.before_loop
async def before_sync_roles():
    await bot.wait_until_ready()
    logger.info("Role sync task is ready to start")

# Error handler for common exceptions
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Na tento příkaz nemáš oprávnění!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Chybí povinný argument! Použij `!commands` pro nápovědu.")
    else:
        logger.error(f"Unexpected error: {error}", exc_info=True)
        await ctx.send("❌ Nastala neočekávaná chyba. Prosím, zkus to znovu později.")

if __name__ == "__main__":
    try:
        logger.info("Starting bot...")
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
