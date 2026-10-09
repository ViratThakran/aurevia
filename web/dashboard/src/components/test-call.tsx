"use client";

/**
 * A live browser call with the tenant's agent (LiveKit). The API creates the room and sends
 * the agent; the browser only gets a participant token for that one room.
 */
import { Room, RoomEvent, Track } from "livekit-client";
import { useEffect, useRef, useState } from "react";

import { Alert, Button, Select, StatusBadge, formatDuration } from "@/components/ui";
import { api, errorMessage, type Schemas } from "@/lib/api";

type Phase = "idle" | "connecting" | "live" | "ended";
type CallInfo = Schemas["CallResponse"];

interface Line {
  speaker: "you" | "agent";
  text: string;
}

export function TestCall({
  leads,
  onFinished,
}: {
  leads?: { id: string; name: string }[];
  onFinished?: (call: CallInfo) => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [leadId, setLeadId] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<CallInfo | null>(null);
  const room = useRef<Room | null>(null);
  const callId = useRef<string | null>(null);
  const audio = useRef<HTMLDivElement>(null);

  useEffect(() => () => void room.current?.disconnect(), []);

  async function start() {
    setError(null);
    setLines([]);
    setSummary(null);
    setPhase("connecting");
    try {
      const session = await api<Schemas["VoiceSessionResponse"]>("/voice/sessions", {
        method: "POST",
        body: { lead_id: leadId || null },
      });
      callId.current = session.call_id;
      const r = new Room({ adaptiveStream: true, dynacast: true });
      room.current = r;
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) audio.current?.append(track.attach());
      });
      r.on(RoomEvent.Disconnected, () => void finish(false));
      r.registerTextStreamHandler("lk.transcription", async (reader, participant) => {
        const text = (await reader.readAll()).trim();
        if (!text) return;
        const speaker = participant.identity === r.localParticipant.identity ? "you" : "agent";
        setLines((current) => [...current, { speaker, text }]);
      });
      await r.connect(session.livekit_url, session.token);
      await r.localParticipant.setMicrophoneEnabled(true);
      setPhase("live");
    } catch (e) {
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Microphone access was blocked. Allow it in the browser and try again."
          : errorMessage(e),
      );
      // A call that never connected is not a finished call: drop it quietly.
      callId.current = null;
      const r = room.current;
      room.current = null;
      r?.removeAllListeners();
      await r?.disconnect();
      setPhase("idle");
    }
  }

  async function finish(disconnect = true) {
    const r = room.current;
    room.current = null;
    if (r && disconnect) await r.disconnect();
    audio.current?.replaceChildren();
    setPhase("ended");
    const id = callId.current;
    if (!id) return;
    // Give the voice worker a moment to report usage and close the call.
    setTimeout(async () => {
      try {
        const call = await api<CallInfo>(`/voice/calls/${id}`);
        setSummary(call);
        onFinished?.(call);
      } catch (e) {
        setError(errorMessage(e));
      }
    }, 2500);
  }

  return (
    <div className="space-y-4">
      {leads && leads.length > 0 && phase !== "live" ? (
        <label className="block max-w-sm space-y-1">
          <span className="text-sm font-medium">Play a prospect (optional)</span>
          <Select value={leadId} onChange={(e) => setLeadId(e.target.value)}>
            <option value="">No lead: a quick anonymous test</option>
            {leads.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
          <span className="block text-xs text-muted">
            With a lead, the agent remembers this conversation next time.
          </span>
        </label>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        {phase === "live" ? (
          <Button variant="danger" onClick={() => void finish(true)}>
            End call
          </Button>
        ) : (
          <Button onClick={() => void start()} pending={phase === "connecting"}>
            {phase === "ended" ? "Call again" : "Start test call"}
          </Button>
        )}
        <span className="text-sm text-muted">
          {phase === "idle" && "Uses your microphone. The agent speaks first."}
          {phase === "connecting" && "Setting up the call…"}
          {phase === "live" && "Connected: speak naturally, and interrupt whenever you like."}
          {phase === "ended" && "Call ended."}
        </span>
      </div>
      <Alert>{error}</Alert>

      {lines.length > 0 ? (
        <div className="max-h-80 space-y-2 overflow-y-auto rounded-md border border-border bg-background p-3 text-sm">
          {lines.map((line, i) => (
            <p key={i}>
              <span className={line.speaker === "agent" ? "font-medium text-accent" : "font-medium"}>
                {line.speaker === "agent" ? "Agent" : "You"}:
              </span>{" "}
              {line.text}
            </p>
          ))}
        </div>
      ) : null}

      {summary ? (
        <div className="flex flex-wrap gap-4 rounded-md border border-border p-3 text-sm">
          <span>
            Status: <StatusBadge value={summary.status} />
          </span>
          <span>Duration: {formatDuration(summary.started_at, summary.ended_at)}</span>
          <span>Turns: {summary.turn_count}</span>
          {summary.latency?.e2e_p50_ms ? (
            <span>Typical reply time: {(summary.latency.e2e_p50_ms / 1000).toFixed(1)} s</span>
          ) : null}
        </div>
      ) : null}
      <div ref={audio} hidden />
    </div>
  );
}
