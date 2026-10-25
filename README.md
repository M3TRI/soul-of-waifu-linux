# Soul of Waifu for Linux

**[Русская версия](README_RU.md)**

Unofficial Linux port of [Soul of Waifu](https://github.com/jofizcd/Soul-of-Waifu) v2.5.1
by jofizcd. The upstream project ships for Windows only. This port runs on Arch Linux,
Debian, Ubuntu and their derivatives (EndeavourOS, Manjaro, CachyOS, Linux Mint, Zorin OS,
Pop!_OS, ...) and comes with a local LLM out of the box. The installer sets up llama.cpp and a model, and the app talks to it over the
OpenAI-compatible API.

## Server + app edition (branch `docker-split`, testing)

This branch splits the program in two:

- **Server** (Docker containers): the language model (llama.cpp), all voice engines (Kokoro,
  Silero, Edge, XTTSv2, Qwen3-TTS, RVC), speech recognition (Whisper), memory embeddings and
  emotion detection. It needs the GPU; nothing of it is installed into the system itself.
- **App**: the window, Live2D/VRM, microphone and speakers, characters and chats. No torch or
  CUDA (about 1.5 GB instead of 11 GB). It talks to the server by address and token, so one
  server can serve several computers in the local network.

### Install with one command

```bash
curl -fsSL https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux/-/raw/docker-split/install.sh | bash
```

The installer takes no arguments: it asks for the language, shows a summary of your hardware
and system, explains every step and asks before anything that changes the system (packages,
Docker, NVIDIA Container Toolkit). It never installs GPU drivers and never adds you to the
`docker` group. Choose one of three modes:

1. **Everything on this computer** - server + app. You can allow other devices in the local
   network to connect.
2. **Only the server** - for other computers; it prints a pairing string at the end.
3. **Only the app** - connects to an existing server with that pairing string.

The model list only offers models that fit into your video memory next to the voice engines
you pick.

**Pairing string** - `sow://host:port#token=...&fp=...`. Show it again on the server with
`sow-server pair`. The connection is encrypted (the server's own certificate, pinned by its
fingerprint) and protected by the token: share the string only with your own devices. Do not
open the port to the internet; use a VPN for access from outside.

### Commands

| Command | |
|---|---|
| `soul-of-waifu` | start the app (also in the application menu) |
| `sow-server status` / `start` / `stop` / `restart` | server containers |
| `sow-server logs [speech\|llama\|gateway]` | server logs |
| `sow-server pair` | pairing string for another device |
| `sow-server update` | rebuild and restart after `git pull` |

Re-run the installer to change the voice profile, the model or network access. Files:
app in `~/.local/share/soul-of-waifu/app`, server data in `~/.local/share/soul-of-waifu/server`,
server settings in `~/.config/soul-of-waifu/server.env`.

The rest of this README describes the all-in-one desktop build from `main`.

## Install

Requirements: x86-64, Arch Linux, Debian 12+ / Ubuntu 22.04+ or a derivative, about 20 GB
free disk space, and a user with `sudo`. An NVIDIA GPU is optional, but it helps a lot.

The app is the same on every distribution; only the installer script differs, because it
installs the system packages with the distribution's package manager.

**Arch Linux** and derivatives:

```bash
sudo pacman -S --needed git
git clone https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux.git
cd soul-of-waifu-linux
./install_arch.sh
```

**Debian / Ubuntu** and derivatives:

```bash
sudo apt install -y git
git clone https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux.git
cd soul-of-waifu-linux
./install_debian.sh
```

Then open **Soul of Waifu** from the application menu, or run `./launch.sh`.

The first install downloads about 5-8 GB (Python packages, llama.cpp, models) and takes
15-40 minutes. The app is installed in place, inside the cloned folder; nothing is put in
system directories except the system packages.

> **NVIDIA users:** install the proprietary driver first (Ubuntu/Zorin: *Software &
> Updates → Additional Drivers*, or `sudo ubuntu-drivers install`) and reboot. The
> installer reads `nvidia-smi` to pick the right CUDA build. Without a working driver
> it falls back to CPU/Vulkan. On Arch, install `nvidia-open` (or `nvidia-open-dkms`) and
> `nvidia-utils` as described in the [Arch Wiki](https://wiki.archlinux.org/title/NVIDIA).

### Installer options

`install_arch.sh` and `install_debian.sh` take the same options.

| Option | Meaning |
|---|---|
| *(none)* | Detect the hardware automatically |
| `--cpu` | CPU only (no CUDA anywhere) |
| `--torch=cu128\|cu126\|cpu` | PyTorch build (cu128: driver ≥ 570, needed for RTX 50xx; cu126: driver ≥ 525) |
| `--llama=cuda\|vulkan\|cpu` | llama.cpp build (CUDA: NVIDIA driver ≥ 570 and Ubuntu 24.04+ / glibc ≥ 2.38; Vulkan: any GPU) |
| `--no-model` | Do not download the default model |
| `--model-url=URL` | Download this GGUF instead of the default one |

You can re-run the installer at any time. Finished steps are skipped, and your
`llama.conf` is kept.

### Update

```bash
cd soul-of-waifu-linux
git pull
./install_arch.sh     # or ./install_debian.sh
```

## What the installer does

1. Installs system libraries (Qt/OpenGL/audio libraries, ffmpeg, build tools): with
   `pacman -Syu` on Arch (this also updates the system, partial upgrades are not supported
   there; Vulkan drivers for AMD/Intel GPUs are added automatically), with apt on Debian/Ubuntu.
2. Installs [uv](https://docs.astral.sh/uv/) together with Python 3.11, then all Python
   dependencies, into `./.venv` (via `install_linux.sh`). The system Python is not touched.
3. Downloads the official [llama.cpp](https://github.com/ggml-org/llama.cpp) release build
   into `./llama`:
   - **CUDA** if the NVIDIA driver is 570 or newer and the system is Arch or
     Ubuntu 24.04+ / Zorin 18+ (the official CUDA build needs glibc 2.38);
   - **Vulkan** otherwise: AMD, Intel, older NVIDIA drivers, Ubuntu 22.04 / Zorin 17 / Debian 12.
     It runs on NVIDIA GPUs too, through the proprietary driver, and falls back to the CPU if
     no GPU is found.
4. Downloads the app's helper models from HuggingFace (sha256-checked), plus a default chat
   model: [Qwen3-4B-Instruct-2507 Q4_K_M](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF)
   (2.5 GB), saved to `assets/local_llm/`.
5. Writes `llama.conf` with settings that match your GPU memory, and adds a menu entry in
   `~/.local/share/applications/soul-of-waifu.desktop`.

## How it runs

`launch.sh` (also used by the menu entry):

1. If an OpenAI-compatible server already answers on `127.0.0.1:8095`, it uses that server.
2. Otherwise it starts `llama/llama-server` with the model and waits until the model is
   loaded. A desktop notification shows the progress.
3. Then it starts the app. When you close the app, llama-server is stopped.

The app is preconfigured to talk to this server: conversation method **Local LLM** with
an external server at `http://127.0.0.1:8095/v1`. See *Options → LLM Settings → Advanced →
Hardware & Backend → External server (OpenAI-compatible)*. The model id is detected automatically.

### llama.conf

```bash
LLAMA_PORT=8095     # keep in sync with the Server URL in the app's settings
LLAMA_MODEL=""      # path to a .gguf; empty = first *.gguf in assets/local_llm
LLAMA_CTX=16384     # context size
LLAMA_NGL=""        # GPU layers; empty = fit into free VRAM automatically, 0 = CPU only
LLAMA_WAIT=300      # seconds to wait for the model to load
LLAMA_ARGS=""       # any extra llama-server flags
```

**Other models:** put any `.gguf` file into `assets/local_llm/` (or download one from the
app's Models Hub, which saves there too) and set `LLAMA_MODEL` to it.

**Your own server:** start llama.cpp, LM Studio, Ollama or any other OpenAI-compatible
server on port 8095 before you open the app, and `launch.sh` will use it. To use another
port or host, change the Server URL in the app's settings and `LLAMA_PORT` in `llama.conf`.

## Hardware notes

- **4-6 GB VRAM (e.g. RTX 3050/3060 Laptop):** the installer sets an 8K context, a q8_0 KV
  cache and keeps 1.5 GB of VRAM free for speech recognition and TTS. Layers that do not fit
  stay in RAM (llama.cpp `--fit`), which is slower but works. Pick light TTS engines
  (Edge TTS, Kokoro, Silero). Qwen3-TTS and XTTS need about 4 GB of VRAM on their own.
- **8 GB+ VRAM:** the defaults are fine. You can try 8-12B models in Q4_K_M.
- **No GPU:** use `--cpu`. Small models (≤ 4B) are usable on a modern 4-8 core CPU.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Nothing happens when you click the menu entry | Run `./launch.sh` in a terminal to see the error |
| "llama-server exited while loading the model" | See `logs/llama-server.log`; usually out of memory, so lower `LLAMA_CTX` or set `LLAMA_NGL` to a smaller number |
| App says the LLM server is offline | Check that `curl http://127.0.0.1:8095/v1/models` answers and that the port matches the Server URL in the settings |
| No sound / wrong microphone | In *Audio Devices*, pick the `default`, `pipewire` or `pulse` devices |
| Live2D/VRM or web views are black on Wayland | `QT_QPA_PLATFORM=xcb ./launch.sh` |
| Companion overlay windows cannot be dragged on Wayland | Wayland limitation for app-positioned windows; use `QT_QPA_PLATFORM=xcb` |

App logs are in `logs/`.

## Changes compared to upstream

- External OpenAI-compatible server mode for **Local LLM**, with a settings UI and auto-connect.
- Linux fixes: Windows-only imports and idle timer, backslash asset paths, file manager
  integration, Wayland window dragging, PipeWire/PulseAudio device selection (also
  remembered by name), resampling to the output device's native sample rate, mono TTS
  played on both channels of JACK/PipeWire devices, Live2D rendering on Wayland (desktop
  OpenGL context), and WebGL for the VRM view on NVIDIA + Wayland (NVIDIA EGL pinned in
  `start.sh`).
- TTS fixes: model loading no longer counts against the per-sentence timeout, and Qwen3-TTS
  is loaded fully onto the GPU.
- Windows-only features are unchanged and do not work here: PC control tools and the built-in
  llama.cpp updater.

## License and credits

[Soul of Waifu](https://github.com/jofizcd/Soul-of-Waifu) © jofizcd, GPL-3.0. This port is
distributed under the same license (see [LICENSE](LICENSE)). The llama.cpp, PyTorch and
HuggingFace models it downloads come under their own licenses.
