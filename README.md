# layer-whisper

OpenAI Whisper local speech-to-text for OpenCharly images, GPU-capable.

The `whisper` candy installs [openai-whisper](https://github.com/openai/whisper)
via pixi into the default environment, composing the `python`, `cuda`, and
`ffmpeg` layers (ffmpeg is required for audio decoding). The whisper CLI lands in
the pixi default env and runs offline against local models.

## What it provides

| Property | Value |
|---|---|
| Layer / candy | `whisper` |
| Binary | `~/.pixi/envs/default/bin/whisper` |
| Requires | `layer-python`, `layer-cuda`, `layer-ffmpeg` |
| Env files | `charly.yml`, `pixi.toml` |
| Service / port | none |

## How to use it

Compose the layer by pinning this repo in a box's `candy:` list:

```yaml
my-stt-box:
  candy:
    base: fedora
    candy:
      - '@github.com/opencharly/layer-whisper:v2026.243.0516'
```

Then, inside the built image:

```bash
whisper --help                       # usage
whisper audio.mp3 --model base       # transcribe with a local model
```

The candy's `plan:` asserts the whisper CLI in the pixi default env, that it runs
and prints `--model` in its usage, and that `ffmpeg` is on PATH for decoding.

## Layout

- `charly.yml` — the `whisper:` candy entity (the `require:` list, the `check:`
  assertions) and the embedded `whisper-skill:` skill entity.
- `pixi.toml` / `pixi.lock` — the pixi environment that installs `openai-whisper`.
- `CHANGELOG/` — per-CalVer release history.
- `.github/workflows/tag-on-merge.yml` — CalVer tag + `CHANGELOG/` on merge.
- `README.md` — this user overview.

## Related

- Owning skill: `/charly-tools:whisper`
- `/charly-languages:python` — Python runtime (required)
- `/charly-distros:cuda` — CUDA toolkit (required)
- `/charly-selkies:ffmpeg` — FFmpeg multimedia with nonfree codecs (required)
- `/charly-tools:sherpa-onnx` — alternative STT engine (ONNX-based, lighter weight)
- [`opencharly/charly`](https://github.com/opencharly/charly) — the charly CLI and image builder
- [`opencharly/opencharly`](https://github.com/opencharly/opencharly) — the umbrella
