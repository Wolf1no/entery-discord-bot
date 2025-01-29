import asyncio
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope
import logging
from twitchAPI.helper import build_url, build_scope

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
        
        try:
            # Manually construct the auth URL instead of using the browser flow
            params = {
                'client_id': self.client_id,
                'redirect_uri': self.redirect_uri,
                'response_type': 'code',
                'scope': build_scope(self.auth_scope),
                'force_verify': 'false'
            }
            url = build_url('https://id.twitch.tv/oauth2/authorize', params)
            return url
            
        except Exception as e:
            logger.error(f"Error generating auth URL: {e}")
            return None

    async def set_user_auth(self, auth_code):
        try:
            if auth_code.startswith('http'):
                # Extract the code from the full URL if provided
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(auth_code)
                params = parse_qs(parsed.query)
                if 'code' in params:
                    auth_code = params['code'][0]
                else:
                    raise ValueError("No authorization code found in URL")

            if not self.twitch:
                await self.initialize()

            # Create a new UserAuthenticator for token exchange
            self.auth = UserAuthenticator(
                self.twitch,
                self.auth_scope,
                self.redirect_uri
            )
            
            # Exchange the code for tokens
            token, refresh_token = await self.auth.authenticate(auth_code)
            await self.twitch.set_user_authentication(token, refresh_token, self.auth_scope)
            logger.info("User authentication set successfully")
            return True

        except Exception as e:
            logger.error(f"Error setting user auth: {e}")
            return False
