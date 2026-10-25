#!/usr/bin/env bash
# Builds the server images of the current commit and pushes them to the project registry,
# tagged with the git tree hash of server/ (what installer/lib/server.sh pulls). Needs a
# `docker login registry.gitlab.projectmiku.cc` with push rights and a clean server/ folder.
#   tools/publish_images.sh [cu128 cu126 cpu]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
REPO=registry.gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux
[ -z "$(git status --porcelain -- server)" ] || { echo "server/ has uncommitted changes" >&2; exit 1; }
TAG=$(git rev-parse --short=12 HEAD:server)
FLAVOURS=("${@:-cu128 cu126 cpu}")
# shellcheck disable=SC2206
FLAVOURS=(${FLAVOURS[*]})

docker build -f server/gateway/Dockerfile -t "$REPO/gateway:$TAG" .
docker push "$REPO/gateway:$TAG"
for torch in "${FLAVOURS[@]}"; do
    docker build -f server/speech/Dockerfile --build-arg TORCH="$torch" -t "$REPO/speech:$TAG-$torch" .
    docker push "$REPO/speech:$TAG-$torch"
    # The speech images are ~17 GB each; keep only what this machine runs.
    [ "$torch" = "${KEEP_TORCH:-cu128}" ] || docker rmi "$REPO/speech:$TAG-$torch"
done
echo "Published $REPO {gateway,speech}:$TAG"
