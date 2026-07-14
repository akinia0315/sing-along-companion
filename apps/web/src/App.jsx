import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api.js";
import { detectPitch, noteForHz } from "./pitchDetector.js";

function formatTime(value = 0) {
  const seconds = Math.max(0, Math.floor(value / 1_000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function activeLyric(lines, position) {
  if (!lines.length) return { current: null, next: null };
  const index = lines.findLastIndex((line) => line.at_ms <= position + 180);
  if (index < 0) return { current: lines[0], next: lines[1] || null };
  return { current: lines[index], next: lines[index + 1] || null };
}

function linePath(points, width, height, maximumX, minimumY, maximumY) {
  if (!points.length || maximumX <= 0 || maximumY <= minimumY) return "";
  return points.map((point, index) => {
    const x = (point.t_ms / maximumX) * width;
    const y = height - ((point.hz - minimumY) / (maximumY - minimumY)) * height;
    return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function PitchGraph({ localSamples, referenceFrames }) {
  const local = localSamples.map((sample) => ({ t_ms: sample.t_ms, hz: sample.hz }));
  const reference = referenceFrames.slice(0, 180).map((frame) => ({ t_ms: frame.t_ms, hz: frame.hz }));
  const all = [...local, ...reference];
  const minHz = Math.max(50, Math.min(...all.map((point) => point.hz), 120) - 20);
  const maxHz = Math.max(260, Math.max(...all.map((point) => point.hz), 260) + 20);
  const localDuration = Math.max(3_000, ...local.map((point) => point.t_ms));
  const referenceDuration = Math.max(1, ...reference.map((point) => point.t_ms));
  const localPath = linePath(local, 640, 148, localDuration, minHz, maxHz);
  const referencePath = linePath(reference, 640, 148, referenceDuration, minHz, maxHz);
  return (
    <div className="pitch-graph" aria-label="音高走势示意图">
      <svg viewBox="0 0 640 148" preserveAspectRatio="none" role="img">
        <line x1="0" x2="640" y1="37" y2="37" className="grid-line" />
        <line x1="0" x2="640" y1="74" y2="74" className="grid-line" />
        <line x1="0" x2="640" y1="111" y2="111" className="grid-line" />
        {referencePath && <path d={referencePath} className="reference-path" />}
        {localPath && <path d={localPath} className="local-path" />}
      </svg>
      <div className="graph-key"><span><i className="local-dot" />本地音高</span><span><i className="reference-dot" />示例参考线</span></div>
    </div>
  );
}

function MessageList({ messages }) {
  if (!messages.length) return <p className="empty-copy">在这里问“现在唱到哪一句？”试试歌词上下文注入。</p>;
  return (
    <div className="messages">
      {messages.map((message) => (
        <article className={`message ${message.role}`} key={message.id}>
          <small>{message.role === "user" ? "你" : "一起听助手"}{message.kind === "singing_receipt" ? " · 跟唱回执" : ""}</small>
          <p>{message.content}</p>
        </article>
      ))}
    </div>
  );
}

export default function App() {
  const [room, setRoom] = useState(null);
  const [lyrics, setLyrics] = useState([]);
  const [referenceFrames, setReferenceFrames] = useState([]);
  const [profile, setProfile] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sharePitch, setSharePitch] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [localSamples, setLocalSamples] = useState([]);
  const [singing, setSinging] = useState(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const captureRef = useRef(null);
  const sessionRef = useRef(null);
  const pendingSamplesRef = useRef([]);
  const localSamplesRef = useRef([]);
  const queuedUpdateRef = useRef(Promise.resolve());

  const refreshMessages = useCallback(async () => {
    const result = await api.messages();
    setMessages(result.messages);
  }, []);

  const loadSongData = useCallback(async (songId) => {
    if (!songId) return;
    const [lyricResult, referenceResult, profileResult] = await Promise.all([
      api.lyrics(songId),
      api.referencePitch(songId),
      api.profile(songId),
    ]);
    setLyrics(lyricResult.lines || []);
    setReferenceFrames(referenceResult.pitch?.frames || []);
    setProfile(profileResult.profile || null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [roomResult] = await Promise.all([api.room(), refreshMessages()]);
      setRoom(roomResult.room);
      await loadSongData(roomResult.room.current_song?.id);
    } catch (error) {
      setNotice(error.message || "无法连接演示 API");
    }
  }, [loadSongData, refreshMessages]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => api.subscribe((event, payload) => {
    if ((event === "snapshot" || event === "room") && payload.room) setRoom(payload.room);
    if (event === "singing" && payload.session) setSinging(payload.session);
  }), []);

  useEffect(() => {
    if (!room?.is_playing || !room.current_song) return undefined;
    const duration = room.current_song.duration_ms;
    const timer = window.setInterval(() => {
      setRoom((previous) => {
        if (!previous?.is_playing) return previous;
        const position = Math.min(previous.position_ms + 1_000, duration);
        if (position >= duration) {
          void api.controlRoom("pause", position).catch(() => {});
          return { ...previous, is_playing: false, position_ms: position };
        }
        void api.controlRoom("seek", position).catch(() => {});
        return { ...previous, position_ms: position };
      });
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [room?.current_song, room?.is_playing]);

  const queueSharedSamples = useCallback((elapsedMs) => {
    const session = sessionRef.current;
    if (!session || !pendingSamplesRef.current.length) return queuedUpdateRef.current;
    const batch = pendingSamplesRef.current.splice(0, 32);
    queuedUpdateRef.current = queuedUpdateRef.current
      .catch(() => undefined)
      .then(async () => {
        const result = await api.updateSinging(session.session_id, elapsedMs, batch);
        if (sessionRef.current?.session_id === session.session_id) {
          sessionRef.current = result.session;
          setSinging(result.session);
        }
      });
    return queuedUpdateRef.current;
  }, []);

  const releaseMicrophone = useCallback(() => {
    const capture = captureRef.current;
    if (!capture) return;
    window.clearInterval(capture.pitchTimer);
    window.clearInterval(capture.shareTimer);
    capture.stream.getTracks().forEach((track) => track.stop());
    void capture.context.close();
    captureRef.current = null;
  }, []);

  const stopPitchCapture = useCallback(async () => {
    const capture = captureRef.current;
    if (!capture) return;
    setCapturing(false);
    window.clearInterval(capture.pitchTimer);
    window.clearInterval(capture.shareTimer);
    const elapsedMs = Math.round(performance.now() - capture.startedAt);
    await queueSharedSamples(elapsedMs);
    await queuedUpdateRef.current.catch(() => undefined);
    const session = sessionRef.current;
    releaseMicrophone();
    sessionRef.current = null;
    pendingSamplesRef.current = [];
    if (!session) {
      setNotice("本地音高已停止；没有上传任何麦克风数据。");
      return;
    }
    try {
      const result = await api.stopSinging(session.session_id, elapsedMs);
      setSinging(result.session || null);
      if (result.reply) await refreshMessages();
      setNotice(result.reply ? "跟唱回执已作为主聊天中的一条回复加入。" : "跟唱片段太短，未写入聊天。");
    } catch (error) {
      setNotice(error.message || "停止跟唱时出错");
    }
  }, [queueSharedSamples, refreshMessages, releaseMicrophone]);

  useEffect(() => () => { releaseMicrophone(); }, [releaseMicrophone]);

  const startPitchCapture = useCallback(async () => {
    if (!room?.current_song || capturing) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setNotice("此浏览器不支持麦克风音高检测。");
      return;
    }
    setBusy(true);
    setNotice(sharePitch ? "正在请求麦克风；仅会共享稀疏音高点。" : "正在请求麦克风；音高将只留在此浏览器内存中。");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: true },
      });
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      const context = new AudioContextClass();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 2_048;
      analyser.smoothingTimeConstant = 0;
      source.connect(analyser);
      const startedAt = performance.now();
      let session = null;
      if (sharePitch) {
        const result = await api.startSinging(room.current_song.id, room.position_ms);
        session = result.session;
        sessionRef.current = session;
        setSinging(session);
      }
      pendingSamplesRef.current = [];
      localSamplesRef.current = [];
      setLocalSamples([]);
      const buffer = new Float32Array(analyser.fftSize);
      const pitchTimer = window.setInterval(() => {
        analyser.getFloatTimeDomainData(buffer);
        const pitch = detectPitch(buffer, context.sampleRate);
        if (!pitch.hz || pitch.confidence < 0.55) return;
        const point = { t_ms: Math.round(performance.now() - startedAt), hz: Math.round(pitch.hz * 10) / 10 };
        localSamplesRef.current = [...localSamplesRef.current.slice(-80), point];
        setLocalSamples(localSamplesRef.current);
        if (sessionRef.current) pendingSamplesRef.current.push(point);
      }, 180);
      const shareTimer = window.setInterval(() => {
        const elapsedMs = Math.round(performance.now() - startedAt);
        void queueSharedSamples(elapsedMs).catch((error) => setNotice(error.message || "音高共享暂时中断"));
      }, 1_000);
      captureRef.current = { stream, context, pitchTimer, shareTimer, startedAt };
      setCapturing(true);
      setNotice(session ? "正在跟唱：浏览器只上传稀疏 F0 音高点，不上传录音。" : "正在本地检测音高，不会上传录音或音高点。");
    } catch (error) {
      releaseMicrophone();
      setNotice(error.message || "无法打开麦克风");
    } finally {
      setBusy(false);
    }
  }, [capturing, queueSharedSamples, releaseMicrophone, room, sharePitch]);

  const controlPlayback = useCallback(async (action, position) => {
    try {
      const result = await api.controlRoom(action, position);
      setRoom(result.room);
    } catch (error) {
      setNotice(error.message || "无法更新房间播放状态");
    }
  }, []);

  const sendMessage = useCallback(async (event) => {
    event.preventDefault();
    const clean = text.trim();
    if (!clean || busy) return;
    setBusy(true);
    try {
      const result = await api.sendMessage(clean);
      setMessages((previous) => [...previous, ...result.messages]);
      setText("");
      setNotice(result.listening_context_attached ? `已附带：${result.context_fields.join("、")}` : "这是一条普通聊天消息；未附带一起听上下文。");
    } catch (error) {
      setNotice(error.message || "发送失败");
    } finally {
      setBusy(false);
    }
  }, [busy, text]);

  const lyric = useMemo(() => activeLyric(lyrics, room?.position_ms || 0), [lyrics, room?.position_ms]);
  const song = room?.current_song;
  const currentHz = localSamples.at(-1)?.hz;

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">PRIVACY-FIRST REFERENCE IMPLEMENTATION</p>
        <h1>一起听 · 跟唱 · 主聊天桥接</h1>
        <p>演示只包含合成时间轴与合成参考线，不内置歌曲、账号、录音或个人数据。</p>
      </header>

      <div className="workspace">
        <section className="card listening-card" aria-labelledby="listen-title">
          <div className="section-heading">
            <div><p className="eyebrow">ROOM</p><h2 id="listen-title">{song?.title || "载入房间中"}</h2><p>{song?.artist || ""}</p></div>
            <span className={`status ${room?.is_playing ? "live" : ""}`}>{room?.is_playing ? "演示播放中" : "已暂停"}</span>
          </div>
          <p className="demo-note">这里演示共享播放状态与歌词时间轴；真实音频播放须接入你已获授权的播放器适配器。</p>
          <div className="transport">
            <button type="button" onClick={() => controlPlayback(room?.is_playing ? "pause" : "play")} disabled={!room}>{room?.is_playing ? "暂停" : "播放"}</button>
            <span>{formatTime(room?.position_ms)} / {formatTime(song?.duration_ms)}</span>
          </div>
          <input
            className="seek"
            type="range"
            min="0"
            max={song?.duration_ms || 1}
            value={room?.position_ms || 0}
            onChange={(event) => setRoom((previous) => previous ? { ...previous, position_ms: Number(event.target.value) } : previous)}
            onMouseUp={(event) => controlPlayback("seek", Number(event.currentTarget.value))}
            onTouchEnd={(event) => controlPlayback("seek", Number(event.currentTarget.value))}
            disabled={!room}
            aria-label="播放位置"
          />
          <div className="lyrics">
            <p className="lyric-label">当前示例行</p>
            <p className="current-lyric">{lyric.current?.text || "等待时间轴开始"}</p>
            <p className="next-lyric">下一句：{lyric.next?.text || "—"}</p>
          </div>
          {profile && <div className="outline"><span>声学轮廓</span><span>{profile.energy?.movement || "—"} 能量 · {profile.melody?.movement || "—"} 旋律 · {profile.timbre?.label || "—"} 音色</span></div>}
        </section>

        <section className="card pitch-card" aria-labelledby="pitch-title">
          <div className="section-heading"><div><p className="eyebrow">F0</p><h2 id="pitch-title">本地音高与可选跟唱</h2></div><span className="pitch-reading">{currentHz ? `${currentHz.toFixed(1)} Hz · ${noteForHz(currentHz)}` : "等待声音"}</span></div>
          <PitchGraph localSamples={localSamples} referenceFrames={referenceFrames} />
          <label className="consent">
            <input type="checkbox" checked={sharePitch} onChange={(event) => setSharePitch(event.target.checked)} disabled={capturing} />
            <span><strong>结束时写入跟唱回执</strong><small>明确同意后，才将稀疏 F0 点短暂发给服务器；不会上传音频或转写。</small></span>
          </label>
          <div className="capture-actions">
            {capturing ? <button type="button" className="danger" onClick={() => void stopPitchCapture()}>停止检测</button> : <button type="button" onClick={() => void startPitchCapture()} disabled={busy}>开始本地音高检测</button>}
            <span>{singing?.sample_count ? `已共享 ${singing.sample_count} 个音高点` : "默认只在本地显示"}</span>
          </div>
          <p className="privacy-line">麦克风仅由浏览器读取。未勾选时，音高点也不会离开浏览器。</p>
        </section>

        <section className="card chat-card" aria-labelledby="chat-title">
          <div className="section-heading"><div><p className="eyebrow">MAIN CHAT</p><h2 id="chat-title">同一条聊天线</h2></div></div>
          <MessageList messages={messages} />
          <form className="chat-form" onSubmit={sendMessage}>
            <input value={text} onChange={(event) => setText(event.target.value)} maxLength="4000" placeholder="例如：现在唱到哪一句？" aria-label="聊天消息" />
            <button type="submit" disabled={busy || !text.trim()}>发送</button>
          </form>
        </section>
      </div>
      <p className={`notice ${notice ? "visible" : ""}`} role="status">{notice}</p>
    </main>
  );
}
