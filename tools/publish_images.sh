#!/usr/bin/env bash
# Builds the server images of the current commit and pushes them to the project registry,
# tagged with the git tree hash of server/ (what installer/lib/server.sh pulls). Needs a
# `docker login ghcr.io` with push rights and a clean server/ folder.
# Normally the GitHub Actions workflow (.github/workflows/server-images.yml) does this on the
# GitHub mirror; this script is the manual fallback.
#   tools/publish_images.sh [cu128 cu126 cpu]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
REPO=ghcr.io/m3tri/soul-of-waifu-linux
[ -z "$(git status --porcelain -- server)" ] || { echo "server/ has uncommitted changes" >&2; exit 1; }
TAG=$(git rev-parse --short=12 HEAD:server)
FLAVOURS=("${@:-cu128 cu126 cpu}")
# shellcheck disable=SC2206
FLAVOURS=(${FLAVOURS[*]})

# No provenance/SBOM attestations: docker pushes the attestation manifest in parallel with the
# image manifest it refers to, and the GitLab registry rejects it (MANIFEST_BLOB_UNKNOWN).
BUILD=(docker build --provenance=false --sbom=false)

"${BUILD[@]}" -f server/gateway/Dockerfile -t "$REPO/gateway:$TAG" .
docker push "$REPO/gateway:$TAG"
for torch in "${FLAVOURS[@]}"; do
    "${BUILD[@]}" -f server/speech/Dockerfile --build-arg TORCH="$torch" -t "$REPO/speech:$TAG-$torch" .
    docker push "$REPO/speech:$TAG-$torch"
    # The speech images are ~17 GB each; keep only what this machine runs.
    [ "$torch" = "${KEEP_TORCH:-cu128}" ] || docker rmi "$REPO/speech:$TAG-$torch"
done
echo "Published $REPO {gateway,speech}:$TAG"
