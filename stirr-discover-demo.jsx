import { useState, useEffect, useRef } from "react";

const STIRR_RED = "#E8392A";
const STIRR_YELLOW = "#ffda3a";
const BG_DARK = "#0d0d1a";
const CARD_BG = "#1a1a2e";
const CARD_HOVER = "#252545";
const TEXT_PRIMARY = "#ffffff";
const TEXT_SECONDARY = "#a0a0b0";

// Verified HLS streams from stirr-iptv-feeds data (streams.json)
const CHANNELS = [
  { id: "BBCNews.uk", name: "BBC News", country: "GB", categories: ["news"], logo: "", stream: "https://vs-hls-push-ww-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_news_channel_hd/mobile_wifi_main_sd_abr_v2.m3u8", isLive: true, description: "BBC News — 24-hour breaking news and analysis" },
  { id: "BBCOne.uk", name: "BBC One", country: "GB", categories: ["general"], logo: "", stream: "https://vs-hls-pushb-uk-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_one_hd/pc_hd_abr_v2.m3u8", isLive: true, description: "BBC's flagship channel — drama, entertainment, news" },
  { id: "BBCTwo.uk", name: "BBC Two", country: "GB", categories: ["general"], logo: "", stream: "https://vs-hls-pushb-uk-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_two_hd/pc_hd_abr_v2.m3u8", isLive: true, description: "BBC Two — documentaries, culture, comedy" },
  { id: "BBCFour.uk", name: "BBC Four", country: "GB", categories: ["general"], logo: "", stream: "https://vs-hls-pushb-uk-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_four_hd/mobile_wifi_main_hd_abr_v2.m3u8", isLive: true, description: "BBC Four — arts, music, documentaries, international film" },
  { id: "BBCArabic.uk", name: "BBC Arabic", country: "GB", categories: ["news"], logo: "", stream: "https://vs-hls-pushb-ww-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_arabic_tv/mobile_wifi_main_hd_abr_v2.m3u8", isLive: true, description: "BBC Arabic Television — news for the Middle East & North Africa" },
  { id: "BBCPersian.uk", name: "BBC Persian", country: "GB", categories: ["news"], logo: "", stream: "https://vs-hls-pushb-ww-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_persian_tv/mobile_wifi_main_hd_abr_v2.m3u8", isLive: true, description: "BBC Persian — Farsi-language news from the BBC" },
  { id: "BBCFood.uk", name: "BBC Food", country: "GB", categories: ["lifestyle"], logo: "", stream: "https://d1e9r0b71zfwk7.cloudfront.net/playlist.m3u8", isLive: true, description: "BBC Food — recipes, cooking shows, food culture" },
  { id: "BBCHomeGarden.uk", name: "BBC Home & Garden", country: "GB", categories: ["lifestyle"], logo: "", stream: "https://d11r33s5i066xh.cloudfront.net/playlist.m3u8", isLive: true, description: "BBC Home & Garden — interiors, gardening, DIY" },
  { id: "BBCKids.uk", name: "BBC Kids", country: "GB", categories: ["kids"], logo: "", stream: "https://dmr1h4skdal9h.cloudfront.net/playlist.m3u8", isLive: true, description: "BBC Kids — children's programming from the BBC" },
  { id: "BBCNewsHD.uk", name: "BBC News HD", country: "GB", categories: ["news"], logo: "", stream: "https://vs-hls-push-ww-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_news_channel_hd/mobile_wifi_main_hd_abr_v2.m3u8", isLive: true, description: "BBC News in HD — 720p live stream" },
];

// STIRR local stations — Amagi HLS URLs constructed from epg_channel_id (see stirr-a2ui/agent/tools.py)
// Pattern: https://{prefix8}-{epg_lo}-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8
const STIRR_STATIONS = [
  { callSign: "KOMO", market: "Seattle, WA", dma: "Seattle-Tacoma", group: "Sinclair", stream: "https://amg01058-amg01058c5-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8", description: "ABC affiliate — Seattle news, weather, traffic" },
  { callSign: "WJLA", market: "Washington, D.C.", dma: "Washington DC", group: "Sinclair", stream: "https://amg01066-amg01066c5-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8", description: "ABC affiliate — DC metro news coverage" },
  { callSign: "WNYT", market: "Albany, NY", dma: "Albany", group: "Hubbard", stream: "https://amg01942-amg01942c5-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8", description: "NBC affiliate — Capital Region news" },
  { callSign: "KSTP", market: "Minneapolis, MN", dma: "Minneapolis-St Paul", group: "Hubbard", stream: "https://amg01070-amg01070c5-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8", description: "ABC affiliate — Twin Cities news" },
  { callSign: "KSAT", market: "San Antonio, TX", dma: "San Antonio", group: "Graham", stream: "https://amg01060-amg01060c5-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8", description: "ABC affiliate — San Antonio news" },
  { callSign: "WBFF", market: "Baltimore, MD", dma: "Baltimore", group: "Sinclair", stream: "https://amg01054-amg01054c5-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8", description: "FOX 45 — Baltimore news and sports" },
];

function HlsPlayer({ src }) {
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src) return;
    setLoading(true);
    setError(null);

    // Cleanup previous instance
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    // Native HLS (Safari)
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      const onMeta = () => setLoading(false);
      const onErr = () => setError("Stream unavailable");
      video.addEventListener("loadedmetadata", onMeta);
      video.addEventListener("error", onErr);
      return () => {
        video.removeEventListener("loadedmetadata", onMeta);
        video.removeEventListener("error", onErr);
      };
    }

    // HLS.js for Chrome/Firefox
    let destroyed = false;
    const initHls = () => {
      if (destroyed) return;
      if (!window.Hls?.isSupported()) { setError("HLS not supported in this browser"); return; }
      const hls = new window.Hls({ maxBufferLength: 30, maxMaxBufferLength: 60, enableWorker: true });
      hlsRef.current = hls;
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
        if (!destroyed) { setLoading(false); video.play().catch(() => {}); }
      });
      hls.on(window.Hls.Events.ERROR, (_, data) => {
        if (data.fatal && !destroyed) {
          if (data.type === "networkError") setError("Stream unavailable — may be geo-restricted or offline");
          else setError("Playback error — stream may not be compatible");
        }
      });
    };

    if (window.Hls) {
      initHls();
    } else {
      const script = document.createElement("script");
      script.src = "https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.5.7/hls.min.js";
      script.onload = initHls;
      script.onerror = () => setError("Failed to load HLS.js library");
      document.head.appendChild(script);
    }

    return () => {
      destroyed = true;
      if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null; }
    };
  }, [src]);

  return (
    <div style={{ position: "relative" }}>
      {loading && !error && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          background: "#000", borderRadius: 12, zIndex: 2, minHeight: 240,
        }}>
          <div style={{ color: TEXT_SECONDARY, fontSize: 16, marginBottom: 6 }}>Connecting to stream...</div>
          <div style={{ color: TEXT_SECONDARY, fontSize: 12 }}>Loading HLS manifest</div>
        </div>
      )}
      {error && (
        <div style={{
          padding: 32, textAlign: "center", background: CARD_BG, borderRadius: 12,
          border: "1px solid #333",
        }}>
          <div style={{ color: "#ff6b6b", fontSize: 16, marginBottom: 12 }}>{error}</div>
          <a href={src} target="_blank" rel="noopener noreferrer" style={{
            color: STIRR_YELLOW, fontSize: 13, textDecoration: "underline",
          }}>
            Try opening stream URL directly
          </a>
        </div>
      )}
      <video
        ref={videoRef}
        controls
        playsInline
        style={{
          width: "100%", display: error ? "none" : "block",
          borderRadius: 12, background: "#000", minHeight: loading ? 0 : 240,
        }}
      />
    </div>
  );
}

function LiveBadge() {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      background: STIRR_RED, color: "#fff", fontSize: 11, fontWeight: 700,
      padding: "3px 10px", borderRadius: 4, textTransform: "uppercase", letterSpacing: 0.5,
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: "50%", background: "#fff",
        animation: "pulse 1.5s ease-in-out infinite",
      }} />
      Live
    </span>
  );
}

function ChannelCard({ channel, onClick }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: hovered ? CARD_HOVER : CARD_BG,
        borderRadius: 12, padding: 16, cursor: "pointer",
        transition: "all 0.2s ease",
        transform: hovered ? "scale(1.02)" : "scale(1)",
        boxShadow: hovered ? `0 4px 20px ${STIRR_RED}22` : "none",
        border: `1px solid ${hovered ? STIRR_RED + "44" : "transparent"}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
        <div style={{
          width: 44, height: 44, borderRadius: 10,
          background: channel.categories?.includes("news") ? "#1a2a3a" : "#2a2a4a",
          display: "flex", alignItems: "center", justifyContent: "center",
          overflow: "hidden", flexShrink: 0, fontSize: 18, fontWeight: 800,
          color: channel.categories?.includes("news") ? "#4a9eff" : STIRR_RED,
        }}>
          {channel.callSign || channel.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: TEXT_PRIMARY, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {channel.callSign ? `${channel.callSign} — ${channel.market}` : channel.name}
          </div>
          <div style={{ fontSize: 12, color: TEXT_SECONDARY, marginTop: 2 }}>
            {channel.callSign ? `${channel.dma} · ${channel.group}` : channel.country}
          </div>
        </div>
        {channel.isLive && <LiveBadge />}
      </div>
      <div style={{ fontSize: 13, color: TEXT_SECONDARY, lineHeight: 1.4, marginBottom: 8 }}>
        {channel.description}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {(channel.categories || []).map(cat => (
          <span key={cat} style={{
            background: "#2a2a4a", color: TEXT_SECONDARY, fontSize: 11,
            padding: "3px 8px", borderRadius: 6, textTransform: "capitalize",
          }}>{cat}</span>
        ))}
      </div>
    </div>
  );
}

function PlayerView({ channel, onBack }) {
  return (
    <div>
      <button onClick={onBack} style={{
        background: "none", border: `1px solid ${TEXT_SECONDARY}44`, color: TEXT_PRIMARY,
        padding: "8px 16px", borderRadius: 8, cursor: "pointer", marginBottom: 16,
        fontSize: 13, display: "flex", alignItems: "center", gap: 6,
        transition: "border-color 0.2s",
      }}
        onMouseEnter={e => e.currentTarget.style.borderColor = TEXT_SECONDARY}
        onMouseLeave={e => e.currentTarget.style.borderColor = `${TEXT_SECONDARY}44`}
      >
        <span style={{ fontSize: 16 }}>&#8592;</span> Back to channels
      </button>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
          {channel.callSign ? `${channel.callSign} — ${channel.market}` : channel.name}
        </h2>
        {channel.isLive && <LiveBadge />}
      </div>

      <HlsPlayer src={channel.stream} />

      <p style={{ color: TEXT_SECONDARY, fontSize: 14, marginTop: 12, lineHeight: 1.5 }}>
        {channel.description}
      </p>
    </div>
  );
}

export default function STIRRDiscover() {
  const [view, setView] = useState("grid");
  const [selected, setSelected] = useState(null);
  const [tab, setTab] = useState("bbc");

  const handleSelect = (channel) => {
    setSelected(channel);
    setView("player");
  };

  if (view === "player" && selected) {
    return (
      <div style={{ background: BG_DARK, minHeight: "100vh", padding: 20, fontFamily: "system-ui, -apple-system, sans-serif", color: TEXT_PRIMARY }}>
        <Header />
        <PlayerView channel={selected} onBack={() => { setView("grid"); setSelected(null); }} />
        <style>{styles}</style>
      </div>
    );
  }

  return (
    <div style={{ background: BG_DARK, minHeight: "100vh", padding: 20, fontFamily: "system-ui, -apple-system, sans-serif", color: TEXT_PRIMARY }}>
      <Header />

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
        {[
          { key: "bbc", label: "BBC Channels" },
          { key: "local", label: "STIRR Local News" },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            background: tab === t.key ? STIRR_RED : CARD_BG,
            color: TEXT_PRIMARY, border: "none", padding: "10px 20px",
            borderRadius: 8, cursor: "pointer", fontSize: 14, fontWeight: 600,
            transition: "background 0.2s",
          }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "bbc" && (
        <>
          <p style={{ color: TEXT_SECONDARY, fontSize: 13, marginBottom: 14 }}>
            Live BBC streams from stirr-iptv-feeds · Click any channel to play
          </p>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 14,
          }}>
            {CHANNELS.map(ch => (
              <ChannelCard key={ch.id} channel={ch} onClick={() => handleSelect(ch)} />
            ))}
          </div>
        </>
      )}

      {tab === "local" && (
        <>
          <p style={{ color: TEXT_SECONDARY, fontSize: 13, marginBottom: 14 }}>
            STIRR local news via Amagi HLS · Click any station to play inline
          </p>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 14,
          }}>
            {STIRR_STATIONS.map(s => (
              <ChannelCard
                key={s.callSign}
                channel={{ ...s, isLive: true, categories: ["news", "local"] }}
                onClick={() => handleSelect({ ...s, name: s.callSign, isLive: true, categories: ["news", "local"] })}
              />
            ))}
          </div>
        </>
      )}

      <div style={{
        marginTop: 24, padding: 16, background: CARD_BG, borderRadius: 12,
        borderLeft: `3px solid ${STIRR_YELLOW}`,
      }}>
        <div style={{ fontSize: 13, color: TEXT_SECONDARY }}>
          Powered by <strong style={{ color: STIRR_RED }}>STIRR</strong> + iptv-org community database · {CHANNELS.length} BBC streams · {STIRR_STATIONS.length} local stations
        </div>
      </div>

      <style>{styles}</style>
    </div>
  );
}

function Header() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
      <div style={{
        background: STIRR_RED, color: "#fff", fontWeight: 900, fontSize: 22,
        padding: "8px 18px", borderRadius: 10, letterSpacing: 1.5,
        boxShadow: `0 2px 12px ${STIRR_RED}66`,
      }}>STIRR</div>
      <div>
        <div style={{ fontSize: 20, fontWeight: 700 }}>Discover</div>
        <div style={{ fontSize: 12, color: TEXT_SECONDARY }}>Live channels from around the world</div>
      </div>
    </div>
  );
}

const styles = `
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
  * { box-sizing: border-box; }
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: ${BG_DARK}; }
  ::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
`;
