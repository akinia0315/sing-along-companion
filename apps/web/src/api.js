const baseUrl = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api").replace(/\/$/, "");

async function request(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

export const api = {
  room: () => request("/listen/room"),
  controlRoom: (action, position_ms) => request("/listen/room/control", {
    method: "POST",
    body: JSON.stringify({ action, ...(Number.isFinite(position_ms) ? { position_ms } : {}) }),
  }),
  lyrics: (songId) => request(`/listen/songs/${encodeURIComponent(songId)}/lyrics`),
  referencePitch: (songId) => request(`/listen/songs/${encodeURIComponent(songId)}/reference-pitch`),
  profile: (songId) => request(`/listen/songs/${encodeURIComponent(songId)}/profile`),
  messages: () => request("/chat/messages"),
  sendMessage: (text) => request("/chat/messages", { method: "POST", body: JSON.stringify({ text }) }),
  startSinging: (song_id, song_position_ms) => request("/listen/room/singing/start", {
    method: "POST",
    body: JSON.stringify({ room_id: "demo", song_id, song_position_ms }),
  }),
  updateSinging: (session_id, elapsed_ms, samples) => request("/listen/room/singing/update", {
    method: "POST",
    body: JSON.stringify({ room_id: "demo", session_id, elapsed_ms, samples }),
  }),
  stopSinging: (session_id, elapsed_ms) => request("/listen/room/singing/stop", {
    method: "POST",
    body: JSON.stringify({ room_id: "demo", session_id, elapsed_ms }),
  }),
  subscribe(onEvent) {
    const events = new EventSource(`${baseUrl}/listen/events`);
    for (const eventName of ["snapshot", "room", "singing", "note"]) {
      events.addEventListener(eventName, (event) => {
        try {
          onEvent(eventName, JSON.parse(event.data));
        } catch {
          // A reconnect will deliver another snapshot. Do not surface raw event data.
        }
      });
    }
    return () => events.close();
  },
};
