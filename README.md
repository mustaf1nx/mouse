# Mouse Assistant

Windows client and local Claude backend for a practice quiz environment. Current client: v19-choice-control-index.

Read [the Russian usage guide](GUIDE_RU.md) for setup, controls, supported question types and limitations.

## Source layout

- `src/client_mouse.py`: input triggers, capture validation, indication and text entry.
- `src/server.py`: authenticated local API and model requests.
- `src/dropdown_support.py`: two-stage dropdown handling.
- `tests/`: deterministic queue, validation and schema tests; no paid model calls.
- `windows/*.env.example`: placeholders only.

## Build

On Windows x64 with Python installed, run `./build.ps1`. The tested toolchain is Python 3.14.5 and PyInstaller 6.22.3; package versions are pinned in `requirements-build.lock`.

Build outputs are `windows/MouseAssistant.exe` and `windows/MouseAssistantServer.exe`. Executables are distributed in the release ZIP, not committed to Git. Client configuration is read from `client.env` next to its executable; server configuration from `.env` next to its executable. No credentials are embedded.

## Tests

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

The client supports `--self-test`, which loads packaged imports and exits without starting input hooks. Successful completion is logged to `%LOCALAPPDATA%/MouseAssistant/client.log`.

## Changes in this snapshot

- Single middle click, Mouse 5 and Right Alt triggers.
- v19 single-choice localization: AI option index/count matched to detected radio controls; no movement when detection is ambiguous.
- Local last-choice screenshot and coordinate diagnostics (not committed).
- Question-panel selection under the cursor; vertical-only indication.
- Text answer clipboard fallback and guarded click-to-type on Windows.
- Cursor signal when text or dropdown preparation is ready.
- Ordered multiple-choice queue.
- Dropdown/matching preparation followed by open-menu verification.
- Dropdown context preserved across scrolling with revalidation.
- Strict answer validation, fenced JSON handling and detailed rejection diagnostics.
- Frozen-build configuration paths, stable installation lock and UTF-8 server console.

The dropdown interface remains dependent on screenshot recognition and native menu behavior. Unit tests and startup checks do not establish accuracy on every real quiz or menu. This repository snapshot does not constitute remote deployment.

The v19 client requires a backend returning `choice_index` and `choice_count` for single-choice answers. This repository includes that backend change. Existing older backends must be updated. The downloadable client EXE still needs `client.env` beside it and a running backend; it is not an all-in-one application.
