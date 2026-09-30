#!/usr/bin/env bash
# Downloads YuNet + SFace ONNX weights (Apache-2.0) from the OpenCV Zoo repo.
# These files are Git LFS objects — a plain `curl` on the raw GitHub URL will
# only get you a small LFS pointer text file, not the real binary. This script
# does a proper LFS pull instead.
#
# Requires: git, git-lfs (apt install git-lfs / brew install git-lfs)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEIGHTS_DIR="$SCRIPT_DIR/backend/app/services/face/weights"
TMP_DIR=$(mktemp -d)

mkdir -p "$WEIGHTS_DIR"

git lfs install --skip-repo
git clone --depth 1 --filter=blob:none https://github.com/opencv/opencv_zoo.git "$TMP_DIR"

cd "$TMP_DIR"
git lfs pull --include="models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
git lfs pull --include="models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

cp models/face_detection_yunet/face_detection_yunet_2023mar.onnx "$WEIGHTS_DIR/"
cp models/face_recognition_sface/face_recognition_sface_2021dec.onnx "$WEIGHTS_DIR/"

rm -rf "$TMP_DIR"
echo "Done. Models saved to: $WEIGHTS_DIR"