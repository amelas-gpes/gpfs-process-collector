# GPFS vector presence

The voice interface uses GPFS's supplied mark directly. It does not put a logo over an orb or behind a glow. The four taupe diamonds move on underdamped springs (a composed bounce), the copper interlocking outline sways slightly, and rendered reach is kept inside the outline so the mark always reads as the logo. The live presence and its fallback show the symbol only. The app header shows the official gpfs.com lockup (`web/assets/gpfs-logo.svg`), as the 2022 brand sheet specifies for website headers.

Around the mark, CSS draws the brand's diagonal hatch (`ltDnDiag`, Zircon `#DEE0E4`) as a quiet circular field and a hairline ring that answers real voice activity: Bermuda Grey while listening, an orange hairline ripple while the AI speaks. There is no glow, blur, gradient or recolouring of the mark.

## Official source and fidelity

Retrieved on 2026-11-02 from the official site:

- SVG: <https://gpfs.com/images/logo/rev/rev_gpfs_stacked.svg>
- Brand context: <https://gpfs.com/>
- Site styles inspected: <https://gpfs.com/templates/yootheme_gp/css/custom.css?5.0.53> and <https://gpfs.com/templates/yootheme_gp/css/theme.12.css?1793645790>

`web/assets/gpfs-logo.svg` is the **unmodified 6,971-byte original**. SHA-256:

```text
f7a6179bbe98c6477ff443a646e1253273305460231e888b1f83ef114425002b
```

Its original viewBox is `0 0 129.92136 45.69322`. The source contains 22 vector elements: 17 company-lettering elements and five symbol paths. The original full lockup is retained only as source provenance; its lettering is not rendered by the app. `web/assets/gpfs-symbol.svg` contains only the original final five paths in a `0 0 42 46` viewBox, preserving their geometry, colors and four original diamond transforms. The header and initial fallback use this symbol-only asset. `web/gpfs-presence.js` embeds only those same five paths. Wrapper groups provide movement without reshaping the source path data, and the live symbol has additional viewBox room for movement.

Verified colors:

| Use | Color | Evidence |
| --- | --- | --- |
| Symbol outline | `#C9753A` | Official SVG's copper path |
| Four diamonds | `#8B7D65` | Official SVG fills; the unmodified source lettering uses the same color |
| Website accent | `#DC6E2C` | Site CSS `.uk-text-cookie` and `.primary4`, plus theme button/link styling |

The moving mark retains its source copper/taupe fills. A low-opacity warm surface light is confined to duplicate copies of those same path contours. The mark itself has no blur, filter or exterior glow; diamonds may puff by at most a few percent while speaking or when tapped. The website's accent orange does not replace the source logo colors. The official asset remains GPFS's identity; downloading it does not assert a new license or ownership.

## Conversation behavior

- **Listening:** a poised inward posture; microphone emphasis draws the four diamonds inward and brings surface light toward the center. Quiet speech receives a nonlinear response above a small noise floor. Pauses release gradually.
- **Speaking:** a projecting outward posture driven by actual AI output activity and output amplitude. The light travels outward as emphasis increases. Playback remaining active preserves that posture through phrase pauses; completion returns to listening. Active microphone interruption takes receptive priority.
- **Idle / ended / muted:** the existing pose settles to the composed original arrangement. A muted microphone cannot articulate the mark; actual AI playback can still speak while the microphone is muted.
- **Connecting:** restrained inward activation during the actual connection state. **Processing:** a separate, small outward waiting motion during the actual processing state. Neither represents a percentage or estimated progress.

Pose and audio envelopes carry continuously across state transitions.

## Interaction

The mark is decorative and stays hidden from assistive technology, but it responds to the pointer:

- **Gaze:** a hovering mouse or pen tilts the mark a few degrees toward the pointer; the diamonds lead the outline (parallax). Touch does not trigger gaze.
- **Curiosity:** hovering the mark spreads the diamonds slightly and adds a touch of surface light.
- **Tap:** each diamond twirls a quarter turn with a staggered pop and returns exactly to the source arrangement (the diamonds are square about their own centres). A single orange hairline ring travels outward.
- **Hello and blink:** the mark greets an opened connection with a twirl, says hello once when it first appears, and blinks softly every few seconds while waiting. These ambient moments use owned timers that stop when the panel or document is hidden.

None of these trigger an action. Reduced motion disables all of them.

## Integration contract

The component mounts synchronously and performs no network requests:

```js
const presence = window.GPFSPresence.create(element);
presence.setState("idle");
presence.setAudio({
  input: 0, output: 0,
  inputActive: false, outputActive: false, playbackActive: false,
  muted: false, connected: false
});
presence.setVisible(true);
// At permanent teardown:
presence.dispose();
```

States: `idle`, `connecting`, `listening`, `speaking`, `processing`, `muted`, `ended`. Levels must be finite numbers between zero and one; invalid/out-of-range values are clamped. Connected Live voice only projects after real output activity. For auxiliary question playback without a WebRTC meter, the app's actual audio-element `playing` event may supply `speaking`; the logo then adopts a static projecting posture without inventing an amplitude signal. Explicit conversation labels remain in the app; the decorative vectors are hidden from assistive technology.

Input noise floor is 0.018; output is 0.012. The additional visual envelope attacks in approximately 60 ms for input and 38 ms for output, and releases in 270 ms / 200 ms. Small pose inertia adds continuity. Animation caps at 60 rendered frames per second and sleeps once a silent pose and every spring settle. Panel visibility and document visibility suspend rendering; resuming never replays the hidden interval. Reduced motion removes articulation and animation frames, using a static state illumination change instead. Preference changes are observed at runtime.

`look(x, y)` (each −1…1), `hover(boolean)` and `poke()` drive the pointer behaviours programmatically; `poke()` returns `false` under reduced motion. The component publishes `--voice`, `--gaze-x`, `--gaze-y` and `--hover` on its root for the CSS field and ring. `inspect()` returns a read-only snapshot of the current pose. `sample(milliseconds)` advances and renders a deterministic frame for tests; it never generates audio. Test-only `create(element, {autoStart:false})` disables automatic animation. Snapshot fields are `state`, `mode`, `input`, `output`, `gather`, `project`, `tilt`, `band`, `light`, `gaze`, `hover`, `parts` (five `{x,y,rotation,scale}` objects in source order), `visible`, `reducedMotion`, and `renderCount`.

## Verification boundary

`tests/test_gpfs_presence.cjs` has 26 passing component checks, zero failures and zero skips. They verify the original-source asset hash, faithful symbol-only geometry and absence of rendered lettering, audio direction/attack/release/noise floor, playback gating, phrase pauses, interruption continuity, mute/end behavior, quiet auxiliary playback, actual waiting states, reduced motion, hidden suspension, 60 fps cap, settled render sleep, deterministic inspection and teardown, plus the tap twirl and its exact return, gaze parallax and CSS variables, hover, published voice energy, the connection greeting, and ambient timer ownership.

Those checks use synthetic numeric audio levels and virtual time. They do **not** prove physical microphone sensitivity, speaker sound, acoustic echo cancellation, or the finished screen's visual quality. Browser motion QA and the existing app test suites are reported separately in `BUILD_VERIFICATION.md`; do not infer a live hardware test from a synthetic motion probe.
