# Soul of Waifu for Linux

**[Русская версия](README_RU.md)**

Unofficial Linux port of [Soul of Waifu](https://github.com/jofizcd/Soul-of-Waifu) v2.5.1 by
jofizcd (the original ships for Windows only). Runs on Arch, Debian, Ubuntu, Fedora, openSUSE
and their derivatives.

The program comes in two parts:

- **Server** (Docker containers): the language model (llama.cpp), the voice engines (Kokoro,
  Silero, Edge, XTTSv2, Qwen3-TTS, RVC), speech recognition (Whisper), memory embeddings and
  emotion detection. It is the part that needs a GPU. Nothing of it is installed into the
  system itself.
- **App**: the window, Live2D/VRM, microphone and speakers, your characters and chats. It has
  no torch or CUDA (about 1.5 GB) and talks to the server by address and token, so one server
  with a GPU can serve the laptops and other computers of your home network.

## Install

```bash
curl -fsSL https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux/-/raw/main/install.sh | bash
```

The installer takes no arguments. It asks for the language, shows a summary of your hardware
and system, explains every step and asks before anything that changes the system (packages,
Docker, NVIDIA Container Toolkit). It never installs or replaces GPU drivers and never adds you
to the `docker` group. Pick one of:

1. **Everything on this computer** - server and app. You can allow other devices in the local
   network to connect.
2. **Only the server** - for other computers. It prints a pairing string at the end.
3. **Only the app** - connects to an existing server with that string.
4. **Remove Soul of Waifu**.

Requirements: x86-64, about 25 GB free disk space for the server (5 GB for the app only), a
user with `sudo`. A GPU is optional but makes a big difference; for an NVIDIA GPU install the
proprietary driver first and reboot.

### Voices and the model

The voice engines and the language model share the GPU's memory. The installer asks which voices
you will use (standard / with voice cloning / with RVC), then lists only the models that fit into
what is left, with a 16k-token context. Measured on a 16 GB card: standard voices leave 13.3 GB
for the model (up to Qwen3 14B), voice cloning 9.4 GB, cloning with RVC 8.2 GB. XTTSv2 is offered
only after you accept its licence (Coqui CPML, non-commercial).

Run the installer again to change the voice profile, the model or network access. More models:
the app's Models Hub downloads them to the server.

## Connecting other devices

On the server computer, `sow-server pair` shows the pairing string
(`sow://host:port#token=...&fp=...`). Paste it into the installer on the other computer (mode 3)
or into the app: *Settings -> Soul of Waifu Server*. The connection is encrypted with the
server's own certificate, pinned by its fingerprint, and protected by the token: share the string
only with your own devices. Do not open the port to the internet; use a VPN for access from
outside.

## Updates

When a new version is out, the app shows what changed and updates itself with one click: the
program, its Python packages, and the server when it runs on the same computer. A server on
another computer updates with `sow-server update`, or by itself once a day if you allowed that in
the installer. The app warns when the server is older than the app.

## Your data

Characters, chats, memory, settings and API keys live in `~/.local/share/soul-of-waifu/data`,
apart from the program. Updates, removal and reinstalls of the program do not touch them; the
uninstaller asks separately (default: keep). The app's own profile backup still
works as before.

## Commands

| Command | |
|---|---|
| `soul-of-waifu` | start the app (also in the application menu) |
| `sow-server status` / `start` / `stop` / `restart` | server containers |
| `sow-server logs [speech\|llama\|gateway]` | server logs |
| `sow-server pair` | pairing string for another device |
| `sow-server update` | update the server |

Files: app `~/.local/share/soul-of-waifu/app`, server data and models
`~/.local/share/soul-of-waifu/server`, server settings `~/.config/soul-of-waifu/server.env`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The app says the server is not connected | *Settings -> Soul of Waifu Server -> Check*; on the server computer `sow-server status`. Pair again if the server was reinstalled |
| A voice engine is greyed out | Its tooltip says why: licence not accepted or not enough video memory for the chosen voice profile. Run the installer again |
| Not enough video memory | Other programs on the same GPU (games, image generation) take memory too; close them or pick a lighter voice profile or a smaller model |
| No sound / wrong microphone | In *Audio Devices* pick the `default`, `pipewire` or `pulse` devices |
| Live2D/VRM or web views are black on Wayland | `QT_QPA_PLATFORM=xcb soul-of-waifu` |

App logs: `~/.local/share/soul-of-waifu/data/logs`; server logs: `sow-server logs`.

## Changes compared to upstream

- Server/app split described above, with an interactive installer, in-app updates and a user
  data folder that survives reinstalls.
- Linux fixes: Windows-only imports and idle timer, backslash asset paths, file manager
  integration, Wayland window handling and Live2D rendering, WebGL for VRM on NVIDIA + Wayland,
  PipeWire/PulseAudio device selection remembered by name, resampling to the output device's
  rate, mono TTS on both channels of JACK/PipeWire devices.
- Editors and viewers no longer block the main window.
- TTS: model loading does not count against the per-sentence timeout; the RVC pitch is applied
  on every request; Edge TTS updated (the old client is rejected by Microsoft).
- Windows-only features do not work here: PC control tools and the built-in llama.cpp updater.

The earlier all-in-one desktop build (everything in one process, `install_arch.sh` /
`install_debian.sh`) is kept in the [`classic`](https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux/-/tree/classic)
branch.

## License and credits

[Soul of Waifu](https://github.com/jofizcd/Soul-of-Waifu) © jofizcd, GPL-3.0. This port is
distributed under the same license (see [LICENSE](LICENSE)). llama.cpp, PyTorch, the voice
engines and the HuggingFace models it downloads come under their own licenses.
