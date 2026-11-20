"use strict";
// Live voice caption check: the audio-thread half of the microphone tap (see
// tapAudio and captionAudio in web/live-voice.js). Loaded by the page with
// audioWorklet.addModule from this same origin. It keeps nothing: it hands the
// page the microphone as the browser mixed it to one channel, in blocks of about
// 100 ms, each with the audio clock time at its end. The page downsamples it,
// keeps a bounded buffer and drops what arrives while the microphone is muted.
class LiveVoiceTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = Math.max(128, Math.round(sampleRate / 10));
    this.block = new Float32Array(this.size);
    this.length = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    // Nothing connected: no audio, and a block is never joined across the gap.
    if (!channel) {this.length = 0;return true;}
    for (let i = 0; i < channel.length; i++) {
      this.block[this.length++] = channel[i];
      if (this.length === this.size) {
        // The block's buffer is handed over (transferred), which empties it
        // here: the next block is a new one of the same size, never one sized
        // from the block just sent.
        const samples = this.block;
        this.block = new Float32Array(this.size);
        this.length = 0;
        this.port.postMessage({samples, end:currentTime + (i + 1) / sampleRate}, [samples.buffer]);
      }
    }
    return true;
  }
}
registerProcessor("live-voice-tap", LiveVoiceTap);
