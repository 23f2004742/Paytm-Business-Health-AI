/*
  Microphone to a WAV blob.

  Why not MediaRecorder, which is one line
  ----------------------------------------------------------------------------
  Because Chrome's MediaRecorder produces WebM/Opus and Sarvam's speech-to-text
  takes WAV or MP3. Posting a WebM there fails on the network, in a shop, after
  the merchant has already spoken -- the worst possible place to discover a
  format mismatch.

  The Raspberry Pi on the counter already posts 16 kHz mono WAV. Recording the
  same thing in the browser means one format reaches the backend from both
  clients, and the endpoint has one path to get right rather than two.

  ScriptProcessorNode is deprecated in favour of AudioWorklet. It is used
  anyway: an AudioWorklet needs a separate module file served over HTTP, which
  is a build-config problem on a device that may be offline, and this node runs
  in every browser this product targets today.
*/

/** 16 kHz mono is what speech models want; anything more is bytes wasted. */
const TARGET_SAMPLE_RATE = 16000;
const BUFFER_SIZE = 4096;

export interface Recording {
  blob: Blob;
  durationSeconds: number;
}

export interface Recorder {
  stop: () => Promise<Recording>;
  cancel: () => void;
}

export function isRecordingSupported(): boolean {
  if (typeof window === "undefined") return false;
  const audioContext =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  // `mediaDevices` is absent on an insecure origin, which is the case this
  // guard is actually for -- the method itself is always defined when it is.
  return Boolean(audioContext && navigator.mediaDevices);
}

/** Float samples in [-1, 1] to the signed 16-bit PCM a WAV file holds. */
function toPcm16(samples: Float32Array): Int16Array {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    // Clamp before scaling: a sample slightly over 1.0 would wrap to a loud
    // negative click, which reads to a speech model as a consonant.
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return pcm;
}

function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const pcm = toPcm16(samples);
  const buffer = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buffer);

  const writeText = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };

  const byteRate = sampleRate * 2; // mono, 2 bytes per sample

  writeText(0, "RIFF");
  view.setUint32(4, 36 + pcm.length * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true); // PCM header size
  view.setUint16(20, 1, true); // PCM, uncompressed
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeText(36, "data");
  view.setUint32(40, pcm.length * 2, true);

  new Int16Array(buffer, 44).set(pcm);
  return new Blob([buffer], { type: "audio/wav" });
}

/**
 * Start recording. Resolves once the microphone is actually open, so the
 * caller only shows "listening" when the merchant is really being heard.
 */
export async function startRecording(): Promise<Recorder> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });

  const AudioCtor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext;

  // Asking for 16 kHz avoids resampling later. Safari ignores the hint, so the
  // real rate is read back off the context and written into the header rather
  // than assumed -- a wrong rate in the header plays back chipmunked and
  // transcribes as gibberish.
  const context = new AudioCtor({ sampleRate: TARGET_SAMPLE_RATE });
  const sampleRate = context.sampleRate;

  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(BUFFER_SIZE, 1, 1);
  const chunks: Float32Array[] = [];
  let length = 0;

  processor.onaudioprocess = (event) => {
    // The event buffer is reused between callbacks, so this must copy.
    const input = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(input));
    length += input.length;
  };

  // Some browsers never fire onaudioprocess for a node with no output path, so
  // the graph is completed through a silent gain rather than left dangling.
  const mute = context.createGain();
  mute.gain.value = 0;
  source.connect(processor);
  processor.connect(mute);
  mute.connect(context.destination);

  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    processor.disconnect();
    mute.disconnect();
    source.disconnect();
    processor.onaudioprocess = null;
    // Without this the browser keeps showing the recording indicator, which
    // reads to a merchant as "it is still listening to my shop".
    stream.getTracks().forEach((track) => track.stop());
    void context.close();
  };

  return {
    async stop() {
      release();
      const merged = new Float32Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      return {
        blob: encodeWav(merged, sampleRate),
        durationSeconds: length / sampleRate,
      };
    },
    cancel: release,
  };
}
