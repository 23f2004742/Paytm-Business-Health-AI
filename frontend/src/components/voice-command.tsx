"use client";

/*
  One voice command.

  This is the whole promise of the product in a single control, so it sits at
  the top of the dashboard rather than on a page of its own.

  ----------------------------------------------------------------------------
  Why this records audio instead of using the browser's recogniser
  ----------------------------------------------------------------------------
  It used to call the Web Speech API with `lang = "hi-IN"`, which meant the
  merchant had to speak Hindi. Marathi came back as Hindi-shaped nonsense
  because Chrome was scoring it against a Hindi model, and Odia could not come
  back at all: Chrome ships no Odia voice model, so there was no language tag
  that would have worked.

  A language picker would have been the wrong fix. A shopkeeper mid-sale is not
  going to open a dropdown, and the sentence they say is usually mixed anyway
  ("do packet Parle-G, UPI kar diya"). So the mic now records and posts the
  audio, and Sarvam decides what language it was. Nothing in this file names a
  language.

  Typing still works and still goes to /api/ai-box/process, unchanged. The mic
  is the addition, not the requirement -- the real device is a Raspberry Pi on
  the counter posting the same WAV to the same backend.

  Nothing here decides anything. The backend classifies, which is why a
  low-confidence khata update comes back asking for confirmation instead of
  quietly moving money.
*/

import { AnimatePresence, motion } from "framer-motion";
import { Check, Loader2, Mic, Square, Send, Volume2, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { Badge, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";
import { isRecordingSupported, startRecording, type Recorder } from "@/lib/audio";
import type { AiBoxActivity } from "@/types";

/** What getUserMedia actually reports, mapped to something a merchant can act on. */
const MIC_ERRORS: Record<string, string> = {
  NotAllowedError:
    "Microphone access is blocked. Allow it from the icon in the address bar, then try again.",
  NotFoundError: "No microphone was found. Check it is plugged in and selected.",
  NotReadableError: "The microphone is in use by another app. Close it and try again.",
  SecurityError: "The mic needs a secure page. Use localhost or https.",
  default: "Could not open the microphone. Type it instead.",
};

/* Nobody dictates a ledger entry for half a minute; past this it is a hot mic. */
const MAX_RECORDING_SECONDS = 30;
/* Shorter than this is a mis-click, not a sentence. */
const MIN_RECORDING_SECONDS = 0.4;

/* Shown as chips: one per thing Munim can do that a payments app cannot.
   Deliberately three languages, because that is the point of the control. */
const EXAMPLES = [
  { text: "Supplier ko 5000 diye", hint: "money out" },
  { text: "Sagar ke khate mein 200 rupaye baaki hain", hint: "money stuck" },
  { text: "Maggi khatam ho gaya", hint: "shop floor" },
];

/**
 * Speak the reply.
 *
 * Sarvam returns real audio inline, which is what plays when a key is set.
 * Without one the backend says so and the browser's own voice reads the text:
 * worse, but a merchant looking at the counter still hears the answer.
 */
function playReply(result: AiBoxActivity, element: HTMLAudioElement | null) {
  const voice = result.voice;
  if (!voice?.available) return;

  if (voice.audio_data_uri && element) {
    element.src = voice.audio_data_uri;
    // Autoplay can still be refused before the page has been interacted with;
    // the merchant has just clicked the mic, so in practice it is allowed.
    void element.play().catch(() => undefined);
    return;
  }

  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    const utterance = new SpeechSynthesisUtterance(voice.text ?? result.text_response);
    utterance.lang = voice.language_code ?? "hi-IN";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }
}

export function VoiceCommand({ onAction }: { onAction?: () => void }) {
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AiBoxActivity | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recorder = useRef<Recorder | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  /* Whether this browser can record at all. Read from the platform rather than
     stored in state: it is a fact about the device, it never changes while the
     page is open, and the server has to answer `false` so the markup it renders
     matches the first client paint. */
  const supported = useSyncExternalStore(
    () => () => {},
    isRecordingSupported,
    () => false,
  );

  useEffect(() => () => recorder.current?.cancel(), []);

  const finish = useCallback(
    (response: AiBoxActivity) => {
      setResult(response);
      playReply(response, audio.current);
      // The books may have changed, so every screen needs re-reading. This is
      // what makes the numbers on the cards move without a refresh.
      if (response.action_taken) onAction?.();
    },
    [onAction],
  );

  const send = useCallback(
    async (transcript: string) => {
      const value = transcript.trim();
      if (!value || busy) return;

      setBusy(true);
      setError(null);
      try {
        finish(await api.processAiBox(value, "typed"));
        setText("");
      } catch {
        setError("Munim could not be reached. Is the backend running?");
      } finally {
        setBusy(false);
      }
    },
    [busy, finish],
  );

  const stop = useCallback(async () => {
    const active = recorder.current;
    recorder.current = null;
    setRecording(false);
    if (!active) return;

    const { blob, durationSeconds } = await active.stop();
    if (durationSeconds < MIN_RECORDING_SECONDS) {
      setError("That was too short to hear. Hold the mic while you speak.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const response = await api.processAiBoxVoice(blob);
      if (response.heard_nothing) {
        setError(response.text_response || "Nothing was heard. Try again.");
        playReply(response, audio.current);
        return;
      }
      setText("");
      finish(response);
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message
          ? cause.message
          : "Munim could not be reached. Is the backend running?",
      );
    } finally {
      setBusy(false);
    }
  }, [finish]);

  /* Held in a ref so the ticker below can reach the current `stop` without
     listing it as a dependency, which would restart the clock every render.
     Synced in an effect rather than during render, and declared before the
     ticker so it is already current the first time the ticker runs. */
  const stopRef = useRef(stop);
  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);

  /* The recording clock, and the only thing that ends a recording the merchant
     forgot to end. Both live in the interval callback rather than in an effect
     body: a hot mic in a shop is a privacy problem, not just an untidy one. */
  useEffect(() => {
    if (!recording) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      const seconds = (Date.now() - started) / 1000;
      setElapsed(seconds);
      if (seconds >= MAX_RECORDING_SECONDS) void stopRef.current();
    }, 200);
    return () => window.clearInterval(timer);
  }, [recording]);

  async function toggle() {
    if (recording) {
      await stop();
      return;
    }
    setResult(null);
    setError(null);
    setElapsed(0);
    try {
      recorder.current = await startRecording();
      setRecording(true);
    } catch (cause) {
      const name = cause instanceof Error ? cause.name : "";
      setError(MIC_ERRORS[name] ?? MIC_ERRORS.default);
    }
  }

  async function resolve(action: "confirm" | "reject") {
    if (!result) return;
    setBusy(true);
    try {
      if (action === "confirm") {
        setResult(await api.confirmAiBox(result.event_id));
      } else {
        const response = await api.rejectAiBox(result.event_id);
        setResult({
          ...result,
          requires_confirmation: false,
          action_taken: false,
          text_response: response.message,
        });
      }
      onAction?.();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="overflow-hidden border-brand/25">
      {/* Playback target for the Sarvam reply. Never shown: the control above
          is the interface, and a second set of transport buttons would only
          compete with it. */}
      <audio ref={audio} className="hidden" />

      <div className="flex items-center gap-3 border-b border-border bg-brand-soft/60 px-5 py-3">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand text-white">
          <Mic className="size-4" strokeWidth={2.3} aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-brand-strong">Just tell Munim</p>
        </div>
        <span className="ml-auto text-[11px] font-medium text-muted">
          {supported ? "Any Indian language" : "Type, or use the Pi on the counter"}
        </span>
      </div>

      <div className="p-4">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void toggle()}
            disabled={!supported || busy}
            aria-label={recording ? "Stop and send" : "Speak to Munim"}
            aria-pressed={recording}
            className={cn(
              "relative grid size-11 shrink-0 place-items-center rounded-xl transition-colors",
              recording
                ? "bg-negative text-white"
                : "bg-brand text-white hover:bg-brand-strong",
              (!supported || busy) && "cursor-not-allowed opacity-40",
            )}
          >
            {recording ? (
              <>
                <span className="absolute inset-0 animate-ping rounded-xl bg-negative/40" />
                <Square className="relative size-4 fill-current" strokeWidth={2.2} aria-hidden />
              </>
            ) : (
              <Mic className="size-5" strokeWidth={2.2} aria-hidden />
            )}
          </button>

          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void send(text);
            }}
            disabled={recording}
            placeholder={
              recording
                ? `Listening… ${elapsed.toFixed(0)}s — tap to stop`
                : "Bolo ya likho — kisi bhi bhasha mein"
            }
            aria-label="Tell Munim what happened"
            className="h-11 min-w-0 flex-1 rounded-xl border border-border bg-surface-muted px-3.5 text-[14px] outline-none placeholder:text-subtle focus:border-brand focus:bg-surface disabled:opacity-70"
          />

          <Button
            size="md"
            onClick={() => void send(text)}
            disabled={!text.trim() || busy || recording}
            aria-label="Send to Munim"
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Send className="size-4" aria-hidden />
            )}
          </Button>
        </div>

        {!result && !error ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {EXAMPLES.map((example) => (
              <button
                key={example.text}
                type="button"
                onClick={() => void send(example.text)}
                disabled={busy || recording}
                className="rounded-full border border-border bg-surface-muted px-2.5 py-1 text-[11.5px] text-muted transition-colors hover:border-brand/40 hover:text-foreground disabled:opacity-50"
              >
                &ldquo;{example.text}&rdquo;
                <span className="ml-1.5 text-subtle">· {example.hint}</span>
              </button>
            ))}
          </div>
        ) : null}

        <AnimatePresence mode="wait">
          {error ? (
            <motion.p
              key="error"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-3 text-[13px] text-negative"
            >
              {error}
            </motion.p>
          ) : result ? (
            <motion.div
              key={result.event_id}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-3 rounded-xl bg-surface-muted p-3.5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  tone={
                    result.requires_confirmation
                      ? "warning"
                      : result.action_taken
                        ? "positive"
                        : "neutral"
                  }
                >
                  {result.event_type.replaceAll("_", " ").toLowerCase()}
                </Badge>
                <span className="text-[11px] text-subtle">
                  {Math.round(result.confidence * 100)}% sure
                </span>
                {result.voice?.available ? (
                  <button
                    type="button"
                    onClick={() => playReply(result, audio.current)}
                    aria-label="Play the reply again"
                    className="text-subtle transition-colors hover:text-foreground"
                  >
                    <Volume2 className="size-3.5" aria-hidden />
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => setResult(null)}
                  aria-label="Dismiss"
                  className="ml-auto text-subtle hover:text-foreground"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </div>

              {/* What was heard, romanised. A merchant who spoke Odia sees
                  their own sentence in letters they can read back and search,
                  which is also exactly what the matchers acted on. */}
              {result.transcript ? (
                <p className="mt-2 text-[12px] italic text-subtle">
                  &ldquo;{result.transcript}&rdquo;
                </p>
              ) : null}

              <p className="mt-2 text-[14px] font-medium leading-relaxed">
                {result.text_response}
              </p>

              {result.requires_confirmation ? (
                <>
                  <p className="mt-2 text-[12px] text-warning">
                    Nothing has changed yet. Munim will not move money it is unsure about.
                  </p>
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" onClick={() => void resolve("confirm")} disabled={busy}>
                      <Check className="size-3.5" aria-hidden /> Haan, sahi hai
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void resolve("reject")}
                      disabled={busy}
                    >
                      <X className="size-3.5" aria-hidden /> Nahi
                    </Button>
                  </div>
                </>
              ) : null}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </Card>
  );
}
