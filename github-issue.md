# [FEATURE] Enable media playback in Cowork artifact sandbox (video/audio/HLS)

## Summary

Cowork artifacts currently block **all** outbound network access from the sandboxed iframe — including `<video>` elements, `fetch()`, XHR, and HLS.js streaming. This prevents any media-rich plugin from playing video or audio inline.

This is a feature request to enable media playback in Cowork artifacts, unlocking an entire category of media plugins.

## Context

We built a fully functional Cowork plugin ([STIRR Discover](https://github.com/tocarte/stirr-claude-app)) that surfaces live streaming video from 70+ local news stations, 70,000+ global IPTV channels, and BBC streams — with a branded UI rendering as an HTML artifact. The MCP server, skill, and artifact UI all work. The only blocker is the sandbox.

## Systematic Test Results

Repro HTML for several of these checks lives in this repo as `video-test.html` (artifact sandbox diagnostic; the Cloudflare tunnel URL in that file was ephemeral).

| Test | Result | Error |
|------|--------|-------|
| MP4 `<video src="...">` | **Blocked** | `Media load rejected by URL safety check` |
| `fetch()` to public HTTPS | **Blocked** | `Failed to fetch` |
| HLS.js via CORS proxy | **Blocked** | `manifestLoadError (HTTP 0)` |
| `fetch()` to localhost | **Blocked** | `Failed to fetch` |
| `<iframe src="http://localhost:...">` | **Blocked** | No request received by server |
| Cloudflare tunnel (public HTTPS) | **Blocked** | `Failed to fetch` |

**Key observation:** `<script src="https://cdnjs.cloudflare.com/...">` loads successfully (HLS.js loads), but all *runtime* network access is blocked — fetch, XHR, video src, audio src, WebSocket.

## Proposed Solutions (any would work)

1. **Allowlisted network per plugin** — Plugins declare permitted domains in their manifest (e.g., `allowedMediaOrigins: ["*.amagi.tv", "*.akamaized.net"]`). The sandbox permits `<video>`/`<audio>` and fetch to those domains only. Scoped, auditable, opt-in.

2. **Native video/audio artifact type** — A first-class media component in the artifact system. Claude generates a video artifact like it generates HTML/React artifacts today. The platform handles playback securely.

3. **Relaxed sandbox for media elements** — Allow `<video>` and `<audio>` elements to load external sources while keeping `fetch()`/XHR restricted. Media elements consume content rather than exfiltrate data, making them lower risk.

## Why This Matters

- **No AI platform has native inline video.** ChatGPT (Tubi integration) and Gemini both link out. This would make Claude the first.
- **Unlocks a new plugin category.** Video, audio, podcasts, live events, music streaming — every content provider becomes a potential Cowork plugin partner.
- **Community demand.** Related requests: #22903 (real-time visual pipes), #12676 (native video file support), #29602 (sandbox network allowlist issues).
- **Enterprise value.** Companies use video for training, news monitoring, competitive intelligence. Inline playback in Cowork makes these workflows conversational.

## What We Built (ready to ship when unblocked)

- **MCP Server** (5 tools): `search_stirr_content`, `get_stirr_live_channels`, `search_iptv_channels`, `get_iptv_streams`, `get_stirr_local_news`
- **Skill** (stirr-discover): Intent detection (WATCH/KNOW/BROWSE), artifact generation, STIRR brand styling
- **Artifact UI**: 24 live channels across 3 tabs (Global News, BBC, STIRR Local), dark branded UI, live badges, persistent navigation
- **Content**: STIRR VODLIX API + iptv-org (70K+ channels from 250+ countries) + BBC feeds

## Current Workaround

Clicking a channel hands the HLS stream URL to the OS, which opens it in VLC. It works but defeats the purpose of inline playback.

## Environment

- Cowork (Claude Desktop app, macOS)
- HTML artifact (not React — React can't load CDN scripts)
- Tested April 2026

---

*Filed by STIRR / Thinking Media. Happy to provide the plugin package, repo access, or a live demo.*
