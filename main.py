import os
import asyncio
import random
import re
import time
from contextlib import asynccontextmanager
from typing import Optional

import yt_dlp
import httpx
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


PORT = int(os.environ.get("PORT", 8080))


# ─── Lifespan ─────────────────────────────────────────────────────────────────
async def _background_warmup():
    try:
        print("[warmup] Pre-fetching trending...")
        await do_trending()
        print("[warmup] Trending cache ready")
    except Exception as e:
        print(f"[warmup] Failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_background_warmup())
    yield


app = FastAPI(title="VS Home API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def random_ua():
    return random.choice(USER_AGENTS)


INNERTUBE_SEARCH_URL = "https://www.youtube.com/youtubei/v1/search"
INNERTUBE_BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"

# Client configs — ordered from most reliable to least for server/datacenter IPs.
# WEB_EMBEDDED_PLAYER (56) avoids 402s that WEB (1) throws on restricted IPs.
INNERTUBE_CLIENTS = [
    {
        "clientName": "WEB_EMBEDDED_PLAYER",
        "clientVersion": "2.20240101.00.00",
        "clientScreen": "EMBED",
        "clientFormFactor": "UNKNOWN_FORM_FACTOR",
        "x_client_name": "56",
        "x_client_version": "2.20240101.00.00",
    },
    {
        "clientName": "ANDROID_EMBEDDED_PLAYER",
        "clientVersion": "17.36.4",
        "androidSdkVersion": 30,
        "x_client_name": "55",
        "x_client_version": "17.36.4",
    },
    {
        "clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER",
        "clientVersion": "2.0",
        "x_client_name": "85",
        "x_client_version": "2.0",
    },
    {
        "clientName": "WEB",
        "clientVersion": "2.20240617.00.00",
        "x_client_name": "1",
        "x_client_version": "2.20240617.00.00",
    },
]

_client_index: int = 0


def _get_innertube_context() -> tuple[dict, dict]:
    """Return (context_payload, headers) for the current client, rotating on failure."""
    global _client_index
    cfg = INNERTUBE_CLIENTS[_client_index % len(INNERTUBE_CLIENTS)]
    context = {
        "client": {
            "clientName": cfg["clientName"],
            "clientVersion": cfg["clientVersion"],
            "hl": "hi",
            "gl": "IN",
            **{k: v for k, v in cfg.items()
               if k not in ("clientName", "clientVersion", "x_client_name", "x_client_version")},
        }
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": random_ua(),
        "Accept-Language": "hi-IN,hi;q=0.9,en;q=0.8",
        "X-YouTube-Client-Name": cfg["x_client_name"],
        "X-YouTube-Client-Version": cfg["x_client_version"],
        "Origin": "https://www.youtube.com",
        "Referer": "https://www.youtube.com/",
        "X-Origin": "https://www.youtube.com",
    }
    return context, headers


def _rotate_client():
    """Move to next client after repeated failures."""
    global _client_index
    _client_index = (_client_index + 1) % len(INNERTUBE_CLIENTS)
    print(f"[innertube] Rotating to client: {INNERTUBE_CLIENTS[_client_index]['clientName']}")


TRENDING_QUERIES = [
    "viral trending india 2025",
    "new bollywood songs 2025",
    "trending videos india today",
    "popular hindi songs 2025",
]

CHANNEL_VIDEOS_PARAMS = "EgZ2aWRlb3PyBgQKAjoA"


# ─── Models ───────────────────────────────────────────────────────────────────
class VideoItem(BaseModel):
    id: str
    title: str
    thumb: str
    duration: str = ""
    views: str = ""
    channel: str = ""
    channelId: str = ""
    channelAvatar: str = ""
    publishedAt: str = ""


class VideoListResponse(BaseModel):
    results: list[VideoItem]


class StreamInfo(BaseModel):
    title: Optional[str] = None
    stream: Optional[str] = None
    thumb: Optional[str] = None
    source: Optional[str] = None
    error: Optional[str] = None


class HealthStatus(BaseModel):
    status: str


class ChannelInfo(BaseModel):
    id: str
    name: str
    handle: str = ""
    avatar: str = ""
    banner: str = ""
    subscribers: str = ""
    description: str = ""
    videoCount: str = ""
    videos: list[VideoItem] = []


# ─── Cache ────────────────────────────────────────────────────────────────────
_stream_cache: dict = {}
_channel_cache: dict = {}
_trending_cache: dict = {}
_category_cache: dict = {}
CACHE_TTL = 4 * 60
CHANNEL_CACHE_TTL = 10 * 60
TRENDING_CACHE_TTL = 4 * 60
CATEGORY_CACHE_TTL = 10 * 60

CATEGORY_QUERIES: dict = {
    "music": "trending hindi songs bollywood music 2025",
    "gaming": "gaming india trending youtube 2025",
    "news": "india news today hindi latest breaking",
    "sports": "cricket ipl highlights india sports 2025",
    "comedy": "comedy videos hindi stand up india",
    "bollywood": "bollywood new movies songs 2025 hindi",
    "technology": "tech review india hindi 2025 smartphone",
}


def get_cached(cache: dict, key: str) -> Optional[dict]:
    e = cache.get(key)
    if not e:
        return None
    if time.time() > e["_exp"]:
        del cache[key]
        return None
    return {k: v for k, v in e.items() if k != "_exp"}


def set_cache(cache: dict, key: str, data: dict, ttl: int = CACHE_TTL):
    cache[key] = {**data, "_exp": time.time() + ttl}


# ─── InnerTube helpers ────────────────────────────────────────────────────────
def _safe_text(obj: dict, *keys) -> str:
    """Safely traverse nested dict and return string value."""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(k, {})
    return cur if isinstance(cur, str) else ""


def _best_thumbnail(thumbs: list) -> str:
    if not thumbs:
        return ""
    best = max(thumbs, key=lambda t: t.get("width", 0) * t.get("height", 0))
    return best.get("url", "")


def _thumb_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def parse_results(data: dict, limit: int) -> list[VideoItem]:
    """Parse search results from InnerTube search API response."""
    out = []
    try:
        sections = (
            data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )
        for sec in sections:
            for item in sec.get("itemSectionRenderer", {}).get("contents", []):
                vr = item.get("videoRenderer")
                if not vr:
                    continue
                vid_id = vr.get("videoId", "")
                if not vid_id:
                    continue
                title = (vr.get("title", {}).get("runs") or [{}])[0].get("text", "Unknown")
                duration = (vr.get("lengthText") or {}).get("simpleText", "")
                views = (vr.get("viewCountText") or {}).get("simpleText", "")
                byline = (vr.get("longBylineText") or {}).get("runs") or [{}]
                channel = byline[0].get("text", "")
                channel_id = (
                    byline[0]
                    .get("navigationEndpoint", {})
                    .get("browseEndpoint", {})
                    .get("browseId", "")
                )
                avatar = ""
                ctr = (
                    vr.get("channelThumbnailSupportedRenderers", {})
                    .get("channelThumbnailWithLinkRenderer", {})
                    .get("thumbnail", {})
                    .get("thumbnails", [])
                )
                if ctr:
                    avatar = ctr[-1].get("url", "")

                published = (vr.get("publishedTimeText") or {}).get("simpleText", "")
                out.append(VideoItem(
                    id=vid_id,
                    title=title,
                    thumb=_thumb_url(vid_id),
                    duration=duration or "",
                    views=views or "",
                    channel=channel or "",
                    channelId=channel_id or "",
                    channelAvatar=avatar or "",
                    publishedAt=published or "",
                ))
                if len(out) >= limit:
                    return out
    except Exception as e:
        print(f"[parse_results error] {e}")
    return out


def _parse_lockup_video(lvm: dict) -> Optional[VideoItem]:
    """
    Parse a lockupViewModel (YouTube's newer renderer format).
    Structure:
      contentId: videoId
      contentImage.thumbnailViewModel.image.sources[]: thumbnails
      contentImage.thumbnailViewModel.overlays[0].thumbnailBottomOverlayViewModel.badges[0].thumbnailBadgeViewModel.text: duration
      metadata.lockupMetadataViewModel.title.content: title
      metadata.lockupMetadataViewModel.metadata.contentMetadataViewModel.metadataRows[0].metadataParts[0].text.content: views
    """
    try:
        vid_id = lvm.get("contentId", "")
        if not vid_id:
            return None

        title = _safe_text(lvm, "metadata", "lockupMetadataViewModel", "title", "content")
        if not title:
            return None

        # Duration from badge overlay
        duration = ""
        overlays = (
            lvm.get("contentImage", {})
            .get("thumbnailViewModel", {})
            .get("overlays", [])
        )
        for overlay in overlays:
            badge_list = (
                overlay.get("thumbnailBottomOverlayViewModel", {})
                .get("badges", [])
            )
            for badge in badge_list:
                text = _safe_text(badge, "thumbnailBadgeViewModel", "text")
                if text and re.match(r"\d+:\d+", text):
                    duration = text
                    break
            if duration:
                break

        # Views from metadata rows
        views = ""
        rows = (
            lvm.get("metadata", {})
            .get("lockupMetadataViewModel", {})
            .get("metadata", {})
            .get("contentMetadataViewModel", {})
            .get("metadataRows", [])
        )
        if rows:
            parts = rows[0].get("metadataParts", [])
            if parts:
                views = _safe_text(parts[0], "text", "content")

        return VideoItem(
            id=vid_id,
            title=title,
            thumb=_thumb_url(vid_id),
            duration=duration,
            views=views,
        )
    except Exception as e:
        print(f"[lockup parse error] {e}")
        return None


def parse_channel_videos(data: dict, limit: int = 20) -> list[VideoItem]:
    """
    Parse channel video list from InnerTube browse response.
    Handles both old videoRenderer and new lockupViewModel formats.
    Also handles the selected Videos tab in twoColumnBrowseResultsRenderer.
    """
    out: list[VideoItem] = []

    def _extract_from_contents(contents: list) -> list[VideoItem]:
        items: list[VideoItem] = []
        for item in contents:
            # New format: richItemRenderer → lockupViewModel
            ri = item.get("richItemRenderer", {})
            lvm = ri.get("content", {}).get("lockupViewModel")
            if lvm:
                parsed = _parse_lockup_video(lvm)
                if parsed:
                    items.append(parsed)
                    if len(items) >= limit:
                        return items
                continue

            # Old format: richItemRenderer → videoRenderer
            vr = ri.get("content", {}).get("videoRenderer")
            if vr:
                vid_id = vr.get("videoId", "")
                title = (vr.get("title", {}).get("runs") or [{}])[0].get("text", "")
                duration = (vr.get("lengthText") or {}).get("simpleText", "")
                views = (vr.get("viewCountText") or {}).get("simpleText", "")
                if vid_id and title:
                    items.append(VideoItem(
                        id=vid_id, title=title, thumb=_thumb_url(vid_id),
                        duration=duration, views=views,
                    ))
                    if len(items) >= limit:
                        return items
                continue

            # Grid renderer
            grid = item.get("gridRenderer", {})
            for gi in grid.get("items", []):
                gvr = gi.get("gridVideoRenderer", {})
                vid_id = gvr.get("videoId", "")
                title = (gvr.get("title", {}).get("runs") or [{}])[0].get("text", "")
                if vid_id and title:
                    duration = (gvr.get("thumbnailOverlays") or [{}])[0].get(
                        "thumbnailOverlayTimeStatusRenderer", {}
                    ).get("text", {}).get("simpleText", "")
                    items.append(VideoItem(
                        id=vid_id, title=title, thumb=_thumb_url(vid_id), duration=duration,
                    ))
                    if len(items) >= limit:
                        return items
        return items

    # Walk tabs to find selected Videos tab
    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    for tab in tabs:
        tr = tab.get("tabRenderer", {})
        if not tr.get("selected"):
            continue
        content = tr.get("content", {})
        rich_grid = content.get("richGridRenderer", {})
        if rich_grid:
            out = _extract_from_contents(rich_grid.get("contents", []))
            if out:
                return out
        # Fallback: sectionListRenderer
        section_list = content.get("sectionListRenderer", {})
        for sec in section_list.get("contents", []):
            isr = sec.get("itemSectionRenderer", {})
            for sub in isr.get("contents", []):
                grid = sub.get("gridRenderer", {})
                out += _extract_from_contents(
                    [{"gridRenderer": grid}] if grid else []
                )
        if out:
            return out

    return out


async def _innertube_post(url: str, payload: dict) -> dict:
    """POST to InnerTube, rotating clients on 402."""
    last_exc: Exception = RuntimeError("No clients tried")
    for _ in range(len(INNERTUBE_CLIENTS)):
        context, headers = _get_innertube_context()
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    url,
                    params={"prettyPrint": "false"},
                    json={"context": context, **payload},
                    headers=headers,
                )
                if r.status_code == 402:
                    client_name = INNERTUBE_CLIENTS[_client_index % len(INNERTUBE_CLIENTS)]["clientName"]
                    print(f"[innertube] 402 from {client_name}, rotating client...")
                    _rotate_client()
                    last_exc = httpx.HTTPStatusError("402", request=r.request, response=r)
                    continue
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 402:
                _rotate_client()
                last_exc = e
                continue
            raise
    raise last_exc


async def innertube_search(query: str) -> dict:
    return await _innertube_post(INNERTUBE_SEARCH_URL, {"query": query})


async def innertube_browse(browse_id: str, params: str = "") -> dict:
    payload: dict = {"browseId": browse_id}
    if params:
        payload["params"] = params
    return await _innertube_post(INNERTUBE_BROWSE_URL, payload)


async def do_search(query: str, limit: int = 20) -> list[VideoItem]:
    try:
        return parse_results(await innertube_search(query), limit)
    except Exception as e:
        print(f"Search error: {e}")
        return []


async def do_trending(limit: int = 24) -> list[VideoItem]:
    cached = get_cached(_trending_cache, "trending")
    if cached:
        return [VideoItem(**v) for v in cached["results"]]

    tasks = await asyncio.gather(
        *[innertube_search(q) for q in TRENDING_QUERIES],
        return_exceptions=True,
    )
    seen: set = set()
    out: list[VideoItem] = []
    for raw in tasks:
        if isinstance(raw, Exception):
            print(f"[trending task error] {raw}")
            continue
        for item in parse_results(raw, limit):
            if item.id not in seen:
                seen.add(item.id)
                out.append(item)
        if len(out) >= limit:
            break
    result = out[:limit]
    set_cache(_trending_cache, "trending", {"results": [v.model_dump() for v in result]}, TRENDING_CACHE_TTL)
    return result


def _parse_page_header(ph: dict) -> dict:
    """Parse pageHeaderRenderer (newer YouTube channel layout)."""
    pvm = ph.get("content", {}).get("pageHeaderViewModel", {})

    name = _safe_text(pvm, "title", "dynamicTextViewModel", "text", "content")

    # Avatar
    avatar_sources = (
        pvm.get("image", {})
        .get("decoratedAvatarViewModel", {})
        .get("avatar", {})
        .get("avatarViewModel", {})
        .get("image", {})
        .get("sources", [])
    )
    avatar = _best_thumbnail(avatar_sources)

    # Banner - pageHeaderRenderer may not have banner, return empty
    banner = ""

    # Metadata rows
    rows = (
        pvm.get("metadata", {})
        .get("contentMetadataViewModel", {})
        .get("metadataRows", [])
    )
    handle = ""
    subscribers = ""
    video_count = ""
    for i, row in enumerate(rows):
        parts = row.get("metadataParts", [])
        if i == 0 and parts:
            handle = _safe_text(parts[0], "text", "content")
        elif i == 1:
            if len(parts) >= 1:
                subscribers = _safe_text(parts[0], "text", "content")
            if len(parts) >= 2:
                video_count = _safe_text(parts[1], "text", "content")

    return dict(name=name, avatar=avatar, banner=banner, handle=handle,
                subscribers=subscribers, video_count=video_count)


def _parse_c4_header(ch: dict) -> dict:
    """Parse c4TabbedHeaderRenderer (classic YouTube channel layout)."""
    name = ch.get("title", "")
    handle = (ch.get("channelHandleText", {}).get("runs") or [{}])[0].get("text", "")
    avatar_thumbs = ch.get("avatar", {}).get("thumbnails", [])
    avatar = _best_thumbnail(avatar_thumbs)
    banner_thumbs = ch.get("banner", {}).get("thumbnails", [])
    banner = _best_thumbnail(banner_thumbs)
    subscribers = (ch.get("subscriberCountText") or {}).get("simpleText", "")
    video_count = (ch.get("videosCountText", {}).get("runs") or [{}])[0].get("text", "")
    return dict(name=name, avatar=avatar, banner=banner, handle=handle,
                subscribers=subscribers, video_count=video_count)


async def fetch_channel_info(channel_id: str) -> ChannelInfo:
    cached = get_cached(_channel_cache, channel_id)
    if cached:
        return ChannelInfo(**cached)

    # Fetch main page (header info) + Videos tab in parallel
    main_data, videos_data = await asyncio.gather(
        innertube_browse(channel_id),
        innertube_browse(channel_id, params=CHANNEL_VIDEOS_PARAMS),
        return_exceptions=True,
    )

    if isinstance(main_data, Exception):
        raise main_data

    # Parse header
    header = main_data.get("header", {})
    ch = header.get("c4TabbedHeaderRenderer")
    if ch:
        hinfo = _parse_c4_header(ch)
    else:
        ph = header.get("pageHeaderRenderer", {})
        hinfo = _parse_page_header(ph)

    name = hinfo["name"] or channel_id
    avatar = hinfo["avatar"]
    banner = hinfo["banner"]
    handle = hinfo["handle"]
    subscribers = hinfo["subscribers"]
    video_count = hinfo["video_count"]

    # Parse videos from the dedicated Videos tab response
    videos: list[VideoItem] = []
    if not isinstance(videos_data, Exception):
        videos = parse_channel_videos(videos_data, limit=20)

    # Fallback: try parsing from main data if videos tab gave nothing
    if not videos:
        videos = parse_channel_videos(main_data, limit=20)

    info = ChannelInfo(
        id=channel_id,
        name=name,
        handle=handle or "",
        avatar=avatar or "",
        banner=banner or "",
        subscribers=subscribers or "",
        description="",
        videoCount=video_count or "",
        videos=videos,
    )
    set_cache(_channel_cache, channel_id, info.model_dump(), CHANNEL_CACHE_TTL)
    return info


# ─── yt-dlp strategies ────────────────────────────────────────────────────────
# tv_embedded and ios are the most reliable on server/datacenter IPs because
# they do not require PO tokens. WEB requires a valid PO token from 2024 onward.
# mediaconnect / web_safari are newer clients that sometimes bypass restrictions.
STRATEGIES = [
    ("tv_embedded", {
        "extractor_args": {"youtube": {
            "player_client": ["tv_embedded"],
            "skip": ["webpage"],
        }},
    }),
    ("ios", {
        "extractor_args": {"youtube": {
            "player_client": ["ios"],
            "skip": ["webpage"],
        }},
    }),
    ("android_vr", {
        "extractor_args": {"youtube": {
            "player_client": ["android_vr"],
            "skip": ["webpage"],
        }},
    }),
    ("android", {
        "extractor_args": {"youtube": {
            "player_client": ["android"],
            "skip": ["webpage"],
        }},
    }),
    ("android_testsuite", {
        "extractor_args": {"youtube": {
            "player_client": ["android_testsuite"],
            "skip": ["webpage"],
        }},
    }),
    ("mweb", {
        "extractor_args": {"youtube": {
            "player_client": ["mweb"],
            "skip": ["webpage"],
        }},
    }),
    ("web_creator", {
        "extractor_args": {"youtube": {
            "player_client": ["web_creator"],
            "skip": ["webpage"],
        }},
    }),
    ("default", {}),
]

# COOKIES_FILE: set env var YOUTUBE_COOKIES_FILE=/path/to/cookies.txt to enable.
# This is the most reliable fix for 502/bot-detection on server IPs.
# Export cookies from your browser using a cookies.txt extension (Netscape format).
_COOKIES_FILE: str = os.environ.get("YOUTUBE_COOKIES_FILE", "")

# Format preference: format 18 is YouTube's 360p MP4, served via simple CDN
# and often bypasses PO-token requirements. Falls back to best available.
FORMAT_STRING = "18/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/bestvideo+bestaudio/best"

# Stream URL expiry: YouTube signed URLs expire in ~6 hours, cache for 5.5h max
STREAM_CACHE_TTL = int(5.5 * 60 * 60)


def _ytdlp_extract(video_id: str, extra: dict) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": FORMAT_STRING,
        "noplaylist": True,
        "nocheckcertificate": True,
        "skip_download": True,
        "ignoreerrors": False,
        "extractor_retries": 3,
        "socket_timeout": 25,
        "http_headers": {
            "User-Agent": random_ua(),
            "Accept-Language": "hi-IN,hi;q=0.9,en;q=0.8",
        },
        **extra,
    }
    # Use cookies file if available — most reliable fix for server-IP bot detection
    if _COOKIES_FILE and os.path.isfile(_COOKIES_FILE):
        opts["cookiefile"] = _COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        if not info:
            raise ValueError("No info returned")
        url = info.get("url") or ""
        if not url:
            formats = info.get("formats") or []
            # Prefer mp4, then m4a/webm, then anything with a URL
            for ext_pref in ("mp4", "m4a", "webm", None):
                for fmt in reversed(formats):
                    if not fmt.get("url"):
                        continue
                    if ext_pref is None or fmt.get("ext") == ext_pref:
                        url = fmt["url"]
                        break
                if url:
                    break
        if not url:
            raise ValueError("No stream URL found")
        return {"title": info.get("title", video_id), "stream": url, "ext": info.get("ext", "mp4")}


async def get_stream(video_id: str) -> dict:
    cached = get_cached(_stream_cache, video_id)
    if cached:
        # Validate cached URL is not obviously expired (contains expire= param)
        stream_url = cached.get("stream", "")
        if "expire" in stream_url:
            import urllib.parse
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(stream_url).query)
            expire_ts = int((qs.get("expire") or ["0"])[0])
            if expire_ts and time.time() > expire_ts - 300:
                print(f"[stream] Cached URL expired for {video_id}, re-fetching")
                del _stream_cache[video_id]
            else:
                return cached
        else:
            return cached

    errors: list[str] = []
    for name, extra in STRATEGIES:
        try:
            r = await asyncio.to_thread(_ytdlp_extract, video_id, extra)
            entry = {**r, "thumb": _thumb_url(video_id), "source": f"yt-dlp-{name}"}
            set_cache(_stream_cache, video_id, entry, STREAM_CACHE_TTL)
            print(f"[stream OK] {name} → {video_id}")
            return entry
        except Exception as e:
            err_msg = str(e)
            errors.append(f"{name}: {err_msg}")
            print(f"[stream FAIL] {name}: {err_msg}")
            # If error is clearly "video unavailable" (private/deleted), stop early
            if any(kw in err_msg.lower() for kw in ("video unavailable", "private video", "has been removed")):
                print(f"[stream] Video {video_id} is permanently unavailable, stopping retries")
                return {"error": "video_unavailable", "detail": err_msg}

    print(f"[stream] All strategies failed for {video_id}: {errors}")
    return {"error": "stream_unavailable", "detail": "; ".join(errors[-2:])}


# ─── API Routes ───────────────────────────────────────────────────────────────
@app.get("/api/healthz", response_model=HealthStatus)
async def health():
    return HealthStatus(status="ok")


@app.get("/api/yt/trending", response_model=VideoListResponse)
async def trending():
    return VideoListResponse(results=await do_trending())


@app.get("/api/yt/search", response_model=VideoListResponse)
async def search(q: str = Query(...), max: int = Query(20, le=40)):
    return VideoListResponse(results=await do_search(q, max))


@app.get("/api/yt/category", response_model=VideoListResponse)
async def category(name: str = Query(...), max: int = Query(24, le=40)):
    if name not in CATEGORY_QUERIES:
        raise HTTPException(400, f"Unknown category: {name}")
    cached = get_cached(_category_cache, name)
    if cached:
        return VideoListResponse(results=[VideoItem(**v) for v in cached["results"]])
    query = CATEGORY_QUERIES[name]
    results = await do_search(query, max)
    set_cache(_category_cache, name, {"results": [v.model_dump() for v in results]}, CATEGORY_CACHE_TTL)
    return VideoListResponse(results=results)


@app.get("/api/yt/stream", response_model=StreamInfo)
async def stream(id: str = Query(...)):
    data = await get_stream(id)
    err = data.get("error")
    if err and not data.get("stream"):
        # video_unavailable = 404, stream failures = 503 (retryable), not 502
        if err == "video_unavailable":
            raise HTTPException(404, detail="Video unavailable (private or deleted)")
        raise HTTPException(503, detail=f"Could not fetch stream: {data.get('detail', err)}")
    return StreamInfo(
        title=data.get("title"),
        stream=data.get("stream"),
        thumb=data.get("thumb"),
        source=data.get("source"),
        error=data.get("error"),
    )


@app.get("/api/yt/channel", response_model=ChannelInfo)
async def channel(id: str = Query(...)):
    try:
        return await fetch_channel_info(id)
    except Exception as e:
        err_msg = str(e)
        print(f"[channel error] {err_msg}")
        # 404 for clearly missing channels, 503 for transient upstream errors
        if any(kw in err_msg.lower() for kw in ("not found", "404", "channel does not exist")):
            raise HTTPException(404, detail=f"Channel not found: {id}")
        raise HTTPException(503, detail=f"YouTube temporarily unavailable, try again shortly")


@app.get("/api/yt/download")
async def download(request: Request, id: str = Query(...)):
    data = await get_stream(id)
    err = data.get("error")
    if err and not data.get("stream"):
        if err == "video_unavailable":
            raise HTTPException(404, detail="Video unavailable (private or deleted)")
        raise HTTPException(503, detail=f"Could not fetch stream: {data.get('detail', err)}")

    stream_url = data["stream"]
    safe = re.sub(r"[^\w\s\-_().]", "", data.get("title", id)).strip()[:100] or id
    hdrs = {
        "User-Agent": random_ua(),
        "Accept": "*/*",
        "Accept-Language": "hi-IN,hi;q=0.9,en;q=0.8",
    }
    if rng := request.headers.get("range"):
        hdrs["Range"] = rng

    ct = "audio/mp4"
    content_length = None
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            head = await c.head(stream_url, headers=hdrs)
            ct = head.headers.get("content-type", "audio/mp4")
            content_length = head.headers.get("content-length")
    except Exception as e:
        print(f"[HEAD fallback] {e}")

    ext = "webm" if "webm" in ct else "m4a"
    rh = {
        "Content-Disposition": f'attachment; filename="{safe}.{ext}"',
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
    }
    if content_length:
        rh["Content-Length"] = content_length

    async def body():
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as c2:
            async with c2.stream("GET", stream_url, headers=hdrs) as r:
                async for chunk in r.aiter_bytes(65536):
                    yield chunk

    return StreamingResponse(body(), media_type=ct, headers=rh)


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/favicon.svg")
    async def favicon():
        return FileResponse(os.path.join(STATIC_DIR, "favicon.svg"))

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        index = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        return {"error": "Frontend not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
