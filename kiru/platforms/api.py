import os
import re
import asyncio
import httpx # aiohttp se fast HTTP/2 support ke liye
import orjson
import aiofiles
from selectolax.parser import HTMLParser # Sabse fast HTML parser
from dataclasses import dataclass
from typing import Optional
from kiru import app, logger

# Pre-compiled Patterns
TG_LINK_PATTERN = re.compile(r"https?://t\.me/(?:c/)?([^/]+)/(\d+)")

@dataclass(slots=True)
class MusicTrack:
    cdnurl: str
    url: str
    id: str
    key: Optional[str] = None

class FallenApi:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        # HTTP/2 enabled client (Ultra Fast Multiplexing)
        self.limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        self.client = httpx.AsyncClient(
            http2=True, 
            limits=self.limits,
            timeout=httpx.Timeout(20.0, connect=5.0),
            headers={"X-API-Key": self.api_key, "User-Agent": "Fallen/3.0"}
        )
        os.makedirs("downloads", exist_ok=True)

    async def get_track(self, url: str) -> Optional[MusicTrack]:
        """API se track info nikalne ke liye optimized function"""
        endpoint = f"{self.api_url}/api/track"
        params = {"url": url}
        
        try:
            # HTTP/2 use karke request
            resp = await self.client.get(endpoint, params=params)
            if resp.status_code == 200:
                data = orjson.loads(resp.content)
                return MusicTrack(
                    cdnurl=data.get("cdnurl", ""),
                    url=data.get("url", ""),
                    id=data.get("id", ""),
                    key=data.get("key")
                )
        except Exception as e:
            logger.error(f"Fetch Error: {e}")
        return None

    async def fast_html_parse(self, html_content: str, selector: str):
        """Agar kabhi HTML parse karna pade toh ye BeautifulSoup se 10x fast hai"""
        tree = HTMLParser(html_content)
        node = tree.css_first(selector)
        return node.text() if node else None

    async def download_track(self, video_id: str) -> Optional[str]:
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        track = await self.get_track(yt_url)
        
        if not track or not track.cdnurl:
            return None

        # Check for Telegram Link
        tg_match = TG_LINK_PATTERN.match(track.cdnurl)
        if tg_match:
            try:
                chat_id = tg_match.group(1)
                msg_id = int(tg_match.group(2))
                if chat_id.isdigit(): chat_id = int(f"-100{chat_id}")
                
                msg = await app.get_messages(chat_id, msg_id)
                if msg:
                    return await msg.download(file_name=f"downloads/{video_id}.mp3")
            except Exception as e:
                logger.error(f"TG Error: {e}")

        # Direct Stream Download (High Speed)
        save_path = f"downloads/{video_id}.mp3"
        try:
            async with self.client.stream("GET", track.cdnurl) as response:
                if response.status_code != 200:
                    return None
                
                async with aiofiles.open(save_path, "wb") as f:
                    # 1MB buffer for ultra-fast disk write
                    async for chunk in response.aiter_bytes(chunk_size=1024*1024):
                        await f.write(chunk)
            return save_path
        except Exception as e:
            logger.error(f"Download Fail: {e}")
            return None

    async def close(self):
        await self.client.aclose()
