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


INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
INNERTUBE_SEARCH_URL = "https://www.youtube.com/youtubei/v1/search"
INNERTUBE_BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
INNERTUBE_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20240101.00.00",
        "hl": "hi",
        "gl": "IN",
    }
}
TRENDING_QUERIES = [
    "viral trending india 2025",
    "new bollywood songs 2025",
    "trending videos india today",
    "popular hindi songs 2025",
]

INNERTUBE_HEADERS = lambda: {
    "Content-Type": "application/json",
    "User-Agent": random_ua(),
    "Accept-Language": "hi-IN,hi;q=0.9,en;q=0.8",
    "X-YouTube-Client-Name": "1",
    "X-YouTube-Client-Version": "2.20240101.00.00",
    "Origin": "https://www.youtube.com",
    "Referer": "https://www.youtube.com/",
}

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


async def innertube_search(query: str) -> dict:
    params = {"key": INNERTUBE_KEY, "prettyPrint": "false"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            INNERTUBE_SEARCH_URL,
            params=params,
            json={"context": INNERTUBE_CONTEXT, "query": query},
            headers=INNERTUBE_HEADERS(),
        )
        r.raise_for_status()
        return r.json()


async def innertube_browse(browse_id: str, params: str = "") -> dict:
    payload: dict = {"context": INNERTUBE_CONTEXT, "browseId": browse_id}
    if params:
        payload["params"] = params
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            INNERTUBE_BROWSE_URL,
            params={"key": INNERTUBE_KEY, "prettyPrint": "false"},
            json=payload,
            headers=INNERTUBE_HEADERS(),
        )
        r.raise_for_status()
        return r.json()


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


# ─── yt-dlp strategies (no cookies required) ──────────────────────────────────
# Ordered from most reliable to least. tv_embedded + ios work without cookies
# even on datacenter IPs. "skip": ["webpage"] avoids bot-detection consent pages.
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

# Format preference: format 18 is YouTube's 360p MP4, served via simple CDN
# and often bypasses PO-token requirements. Falls back to best available.
FORMAT_STRING = "18/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/bestvideo+bestaudio/best"


def _ytdlp_extract(video_id: str, extra: dict) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": FORMAT_STRING,
        "noplaylist": True,
        "nocheckcertificate": True,
        "skip_download": True,
        "ignoreerrors": False,
        "extractor_retries": 2,
        "socket_timeout": 20,
        "http_headers": {
            "User-Agent": random_ua(),
            "Accept-Language": "hi-IN,hi;q=0.9,en;q=0.8",
        },
        **extra,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        if not info:
            raise ValueError("No info returned")
        url = info.get("url") or ""
        if not url:
            formats = info.get("formats") or []
            # Prefer mp4 formats, then any with a URL
            for fmt in reversed(formats):
                if fmt.get("url") and fmt.get("ext") == "mp4":
                    url = fmt["url"]
                    break
            if not url:
                for fmt in reversed(formats):
                    if fmt.get("url"):
                        url = fmt["url"]
                        break
        if not url:
            raise ValueError("No stream URL found")
        return {"title": info.get("title", video_id), "stream": url}


async def get_stream(video_id: str) -> dict:
    cached = get_cached(_stream_cache, video_id)
    if cached:
        return cached
    for name, extra in STRATEGIES:
        try:
            r = await asyncio.to_thread(_ytdlp_extract, video_id, extra)
            entry = {**r, "thumb": _thumb_url(video_id), "source": f"yt-dlp-{name}"}
            set_cache(_stream_cache, video_id, entry)
            print(f"[stream OK] {name} → {video_id}")
            return entry
        except Exception as e:
            print(f"[stream FAIL] {name}: {e}")
    # Return a soft error — frontend will show friendly message
    return {"error": "yh_unavailable"}


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
    if "error" in data and not data.get("stream"):
        raise HTTPException(502, data["error"])
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
        print(f"[channel error] {e}")
        raise HTTPException(502, f"Failed to fetch channel: {e}")


@app.get("/api/yt/download")
async def download(request: Request, id: str = Query(...)):
    data = await get_stream(id)
    if "error" in data and not data.get("stream"):
        raise HTTPException(502, data["error"])

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
