# Tutoriales en video

Each tutorial is a script (`<nombre>/guion.mjs`): the steps run on the real
app (local, demo club "La Roja") while a voice reads them, with a cursor and
subtitles on screen. When a screen changes, regenerate the video instead of
recording it again.

```bash
cd tutoriales
npm install                       # once
ELEVENLABS_API_KEY=... node hacer.mjs recuperar-contrasena
# → salida/recuperar-contrasena.mp4 + .srt
```

- Requires the local stack (`docker compose up`), Google Chrome and ffmpeg.
- Voice: ElevenLabs ("Isabel", neutral Latin American Spanish,
  `ELEVENLABS_VOICE` to change it). Without a key it falls back to the macOS
  voice, which is enough for a draft.
  Lines are cached in `salida/.voces`: re-recording only pays for the
  lines that changed.
- `texto` is the subtitle; `voz` (optional) is what gets read when it should be
  pronounced differently (e.g. "eslab").
- Record only with demo data: these videos get shared. The load-control
  tutorial gives the demo club its data with
  `python manage.py seed_demo_carga --commit` (it runs it on its own); the
  Resumen one (`resumen-del-dia`) uses `seed_demo_daily --commit`: today's
  check-ins, match jumps, training GPS and recent injuries.
- First step: `antes(t)` runs before the clock starts (e.g. log in) and
  `abre` is the page the video opens on.
- Available in each step's `accion(t)`: `clic`, `escribir`, `rellenar` (fills
  without typing), `señalar`, `resaltar` (frames an element and dims the rest),
  `ver` (smooth scroll), `titulo` (a title over the app), `ir`.
- Target length: 25–35 s for simple flows; longer when something has to be
  explained (e.g. `programar-carga`, ~100 s; `resumen-del-dia`, ~75 s).
