# Iron Man: Skyfall

A 54-second realtime 3D ASCII film for Jarvis. Six camera shots cover
ignition, city pursuit, encirclement, reactor charging, repulsor comeback, and flyaway.
It renders articulated red/gold armor, emissive eyes/chest/palms, world-space
buildings, banking cameras, hostile drones, repulsor beams, ballistic fragments,
smoke and shockwaves. Geometry uses near clipping and reciprocal-depth occlusion.

Drones arrive in staggered waves: early hunters pursue, later wingmen fan out
to flank the suit. Each makes an evasive break under the targeting reticle and
fires two committed bursts toward a predicted interception point. Bolts keep
their world-space trajectory after launch. Repulsor damage disables a drone
before the music-aligned explosion; its captured momentum carries it through
a smoking, sparking tumble. All behavior follows the film clock, so seeking or
skipped frames preserve the same choreography without accumulating simulation state.

The story has three acts, with boundaries tied to the existing score:

- **Pursuit (0-16.533 seconds):** launch, street-level flight, and pursuing hunters.
- **Surrounded (16.533-33.135 seconds):** the suit brakes into a hover; five wingmen
  form an orbiting ring and send staggered crossfire through its predicted position.
  A wide orbit establishes the trap before the camera pushes toward the charging core.
- **Comeback (33.135-54 seconds):** a reactor shockwave opens the counterattack;
  the suit accelerates and disables the remaining attackers. A short quarter-speed
  wind-up precedes the final chest blast, followed by a catch-up release before the
  scheduled damage cue. The final explosion stays on its original music accent,
  and the fly-past provides the ending.

Only the visual motion clock slows during the final wind-up. The recording plays
normally; shot boundaries and explosion cues retain their measured timestamps.

## Camera choreography

The pursuit starts behind the right shoulder, looking ahead through the city.
One hunter crosses close to the lens in the foreground, then the camera overtakes
the suit along an eased arc. The encirclement shot cranes upward to reveal the
orbiting drones and descends before the reactor push-in. The comeback opens wide,
sweeps laterally at a lower angle, then settles into a frontal view for the final
chest blast. Camera roll is restrained so the horizon remains readable. Internal
camera moves blend continuously; the six main shot boundaries retain their music
cues, and the existing fly-past ending remains in place.

Say **Hey Jarvis**, then **play the Iron Man animation**, or run:

```bash
~/Jarvis/bin/jarvis-ironman
```

The command opens the desktop console. Use at least 120 columns and 40 rows for
the most detail. Playback targets 18 FPS and follows elapsed time; actual frame
rate depends on CPU, terminal size and throughput. R cancels/resets. Q closes
the viewer. Completion returns to the normal console. Reopen existing console
viewers once after installing the renderer. The locally installed Avengers score
plays in its own MPV process. It temporarily pauses the library player, then
restores the same track afterwards. No system volume setting is changed. R/reset,
command cancellation, and termination stop both the movie and its score.

## Avengers recording and timing

The source is `~/Downloads/The Avengers - Theme Song.mp3`. The original is kept
unchanged. A 54-second WAV excerpt with a brief fade-in and a two-second fade-out
is stored privately at `data/ironman/avengers-theme.wav`. Audio is excluded from
Git; it is not bundled with source or uploaded for publication.

The clip starts at the beginning of the recording. Shot changes are synchronized
to measured attacks at 8.986, 16.533, 25.078, 33.135, and 47.253 seconds. Ten drone
impacts align with selected score attacks. The renderer follows MPV's audio playhead
with short extrapolation between polls; dropped visual frames do not stretch time.
The final attack starts at 33.135 seconds and the fly-past at 47.253 seconds.

Run `jarvis-ironman --silent` to play without music. `JARVIS_IRONMAN_AUDIO` can
select another prepared 54-second excerpt, but these cues are specific to this
recording. If no audio is installed, the show runs silently. A playback failure
is reported rather than leaving an orphaned player running.

Inspect a still without opening windows or changing runtime status:

```bash
jarvis-ironman --frame 31 --width 144 --height 48
```

This is a fan animation, not an official Marvel production. No external media
or game engine is needed; rendering uses Python's standard library.
