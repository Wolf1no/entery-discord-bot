import os
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope, TwitchAPIException
import json
import logging
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TwitchAuthManager:
    def __init__(self, client_id, client_secret, channel_name, token_file='twitch_tokens.json'):
        self.client_id = client_id
        self.client_secret = client_secret
        self.channel_name = channel_name
        self.token_file = token_file
        self.twitch = None
        self.tokens = None
        
    async def initialize(self):
        try:
            self.twitch = await Twitch(self.client_id, self.client_secret)
            
            # Try to load existing tokens
            if await self.load_tokens():
                await self.refresh_auth()
            else:
                await self.perform_auth()
                
            return self.twitch
            
        except Exception as e:
            logger.error(f"Failed to initialize Twitch API: {e}")
            return None

    async def load_tokens(self):
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    self.tokens = json.load(f)
                    # Check if tokens are expired
                    expires_at = datetime.fromisoformat(self.tokens['expires_at'])
                    if expires_at <= datetime.now():
                        logger.info("Tokens are expired, needs refresh")
                        return False
                    return True
            return False
        except Exception as e:
            logger.error(f"Error loading tokens: {e}")
            return False

    async def save_tokens(self, access_token, refresh_token):
        try:
            expires_at = datetime.now() + timedelta(hours=3)  # Tokens typically expire in 4 hours, we'll refresh at 3
            self.tokens = {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'expires_at': expires_at.isoformat()
            }
            with open(self.token_file, 'w') as f:
                json.dump(self.tokens, f)
            logger.info("Saved new tokens")
        except Exception as e:
            logger.error(f"Error saving tokens: {e}")

    async def perform_auth(self):
        try:
            auth = UserAuthenticator(self.twitch, [
                AuthScope.CHANNEL_READ_SUBSCRIPTIONS,
                AuthScope.CHANNEL_READ_VIPS
            ])
            # This will open a browser window for authentication
            token, refresh_token = await auth.authenticate()
            await self.save_tokens(token, refresh_token)
            await self.twitch.set_user_authentication(token, [
                AuthScope.CHANNEL_READ_SUBSCRIPTIONS,
                AuthScope.CHANNEL_READ_VIPS
            ], refresh_token)
        except Exception as e:
            logger.error(f"Error during authentication: {e}")
            raise

    async def refresh_auth(self):
        try:
            if not self.tokens:
                return await self.perform_auth()
                
            await self.twitch.set_user_authentication(
                self.tokens['access_token'],
                [AuthScope.CHANNEL_READ_SUBSCRIPTIONS, AuthScope.CHANNEL_READ_VIPS],
                self.tokens['refresh_token']
            )
        except TwitchAPIException:
            logger.warning("Failed to refresh tokens, performing new authentication")
            await self.perform_auth()
