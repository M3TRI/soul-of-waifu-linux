#!/usr/bin/env bash
# Exports the shareable Linux tree: git-tracked files (working tree, so staged but
# uncommitted files are included) plus the upstream assets that are kept out of git, with
# the owner's personal data reset to the upstream release state. Not included: Python env,
# llama.cpp, GGUF models and the two large helper-model weights - install_debian.sh fetches
# them on the target machine.
#   tools/make_linux_bundle.sh [OUTPUT.tar.gz]   tarball (default ../Soul-of-Waifu-linux.tar.gz)
#   tools/make_linux_bundle.sh --dir DIR         sync the tree into DIR (keeps DIR/.git)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

MODE=tar OUT=""
if [ "${1:-}" = "--dir" ]; then
    MODE=dir OUT=$(readlink -f "${2:?--dir needs a directory}")
else
    OUT=$(readlink -f "${1:-../Soul-of-Waifu-linux.tar.gz}")
fi
NAME=Soul-of-Waifu
BASE=$(git rev-list --max-parents=0 HEAD)   # untouched upstream v2.5.1 release
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/$NAME"
mkdir -p "$STAGE"

git ls-files -z | tar --null -T - -c | tar -x -C "$STAGE"

# Personal data: API tokens, characters with chat history and generated voice samples go back
# to upstream.
for p in app/configuration/api.json app/configuration/characters app/configuration/characters.json app/voices/qwen_audio; do
    rm -rf "${STAGE:?}/$p"
    git archive "$BASE" -- "$p" | tar -x -C "$STAGE"
done
# Owner-only notes and tooling bound to the owner's machine.
rm -f "$STAGE/PROGRESS.md" "$STAGE/tools/live_external_llm.py" "$STAGE/tools/test_external_llm.py"

# settings.json: keep the Linux/external-LLM defaults, drop this machine's audio devices.
# Taken from HEAD, not the working tree: the app rewrites it on every run with the owner's
# themes, presets and web_auth_token.
git show HEAD:app/configuration/settings.json > "$STAGE/app/configuration/settings.json"
python3 -I - "$STAGE/app/configuration/settings.json" <<'EOF'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
m = data["main_settings"]
m.update({
    "input_device": 0, "output_device_combo_index": 0,
    "input_device_name": "", "output_device_name": "",
    "conversation_method": "Local LLM", "local_llm_external": True,
    "local_llm_base_url": "http://127.0.0.1:8095/v1", "local_llm_model": "",
})
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
    f.write("\n")
EOF

# Upstream assets that are gitignored here (see .gitignore); runtime caches are not shipped.
tar -c --exclude=__pycache__ --exclude='assets/local_llm/*' --exclude='assets/rvc_models/*' \
    --exclude=app/utils/e5-small-en-ru/model.safetensors \
    --exclude=app/utils/emotions/detector/pytorch_model.bin \
    assets app/font app/gui/icons app/utils/e5-small-en-ru app/utils/speech-to-text \
    app/utils/emotions app/utils/ai_clients/9b5ad71b2ce5302211f9c61530b329a4922fc6a4 \
    | tar -x -C "$STAGE"
# User data folders are created at run time as links into ~/.local/share/soul-of-waifu/data
# (app/utils/user_data.py), so the tree ships none of them.

# The exported tree has its own .gitignore: there only machine-local files are ignored.
cat > "$STAGE/.gitignore" <<'EOF'
__pycache__/
*.pyc
*.part
.venv/
# Links into the user data folder (app/utils/user_data.py)
/.soul
/.soul_stage
/Backups
/logs
/app/cache
/app/data
/assets/local_llm
/assets/rvc_models
app/utils/e5-small-en-ru/model.safetensors
app/utils/emotions/detector/pytorch_model.bin
app/utils/ai_clients/backend/_temp/recommended_models_cache.json*
llama/
llama.new/
llama.conf
EOF

if [ "$MODE" = dir ]; then
    mkdir -p "$OUT"
    rsync -a --delete --exclude=/.git "$STAGE/" "$OUT/"
    echo "$OUT synced"
else
    tar -C "$WORK" -czf "$OUT" "$NAME"
    echo "$OUT ($(du -h "$OUT" | cut -f1))"
fi
