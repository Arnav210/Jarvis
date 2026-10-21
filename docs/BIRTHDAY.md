# Temporary birthday protocol

Say **Hey Jarvis**, then **birthday protocol**. Reopen any console viewer that
was already open when this feature was installed. It speaks the configured
message exactly once, without adding a greeting or using AI. The 45-second
screen shows fireworks, a cake, and an Iron Man cameo lighting its candles.
It returns to normal automatically; **R** cancels through the existing reset.
**Q** closes the viewer only.

Private settings live at `data/birthday-protocol.json`: `enabled`, `date` in
YYYY-MM-DD, `honoree`, and the exact `message`. The command only plays when
enabled and the machine's local date matches the configured date. Nothing plays
at startup. Say **Hey Jarvis, disable birthday protocol** to disable it early.
The birthday speech is not saved as the repeat-last-message response. No music
track or system audio setting is changed by this feature.
