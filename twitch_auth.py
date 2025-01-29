import asyncio
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope
import logging

logger = logging.getLogger(__name__)

class TwitchAuthManager:
    def __init__(self, client_id, client_secret, channel_name, port=17563):
        self.client_id = client_id
        self.client_secret = client_secret
        self.channel_name = channel_name
        self.twitch = None
        self.port = port
        self.redirect_uri = f'http://localhost:{self.port}'
        self.auth_scope = [
            AuthScope.CHANNEL_READ_SUBSCRIPTIONS,
            AuthScope.USER_READ_EMAIL,
            AuthScope.CHANNEL_READ_VIPS
        ]
        self.auth = None

    async def initialize(self):
        self.twitch = await Twitch(self.client_id, self.client_secret)
        return self.twitch

    async def generate_auth_url(self):
        if not self.twitch:
            await self.initialize()
        
        self.auth = UserAuthenticator(self.twitch, self.auth_scope, force_verify=False, url=self.redirect_uri)
        return await self.auth.generate_url()  # Use generate_url() instead of url property

    async def set_user_auth(self, auth_code):
        try:
            if not self.auth:
                self.auth = UserAuthenticator(self.twitch, self.auth_scope, force_verify=False, url=self.redirect_uri)
            
            token, refresh_token = await self.auth.authenticate(auth_code)
            await self.twitch.set_user_authentication(token, refresh_token, self.auth_scope)
            logger.info("User authentication set successfully")
            return True
        except OSError as e:
            if e.errno == 98:  # Address already in use
                logger.warning(f"Port {self.port} is already in use. Trying another port.")
                self.port += 1
                self.redirect_uri = f'http://localhost:{self.port}'
                return await self.set_user_auth(auth_code)
            else:
                logger.error(f"Error setting user auth: {e}")
                return False
        except Exception as e:
            logger.error(f"Error setting user auth: {e}")
            return False
