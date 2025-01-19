import asyncio
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope
import logging

logger = logging.getLogger(__name__)

class TwitchAuthManager:
    def __init__(self, client_id, client_secret, channel_name):
        self.client_id = client_id
        self.client_secret = client_secret
        self.channel_name = channel_name
        self.twitch = None
        self.redirect_uri = 'http://localhost:17563'
        self.auth_scope = [
            AuthScope.CHANNEL_READ_SUBSCRIPTIONS,
            AuthScope.USER_READ_EMAIL,
            AuthScope.CHANNEL_READ_VIPS
        ]

    async def initialize(self):
        self.twitch = await Twitch(self.client_id, self.client_secret)
        return self.twitch

    async def generate_auth_url(self):
        auth = UserAuthenticator(self.twitch, self.auth_scope, force_verify=False, url=self.redirect_uri)
        return auth.get_auth_url()

    async def set_user_auth(self, auth_code):
        try:
            auth = UserAuthenticator(self.twitch, self.auth_scope, force_verify=False, url=self.redirect_uri)
            token, refresh_token = await auth.authenticate(auth_code)
            await self.twitch.set_user_authentication(token, refresh_token, self.auth_scope)
            logger.info("User authentication set successfully")
            return True
        except Exception as e:
            logger.error(f"Error setting user auth: {e}")
            return False
