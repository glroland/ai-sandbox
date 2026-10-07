#!/usr/bin/env bash
set -euo pipefail

DEST_DIR="/tmp/openai"

mkdir -p "$DEST_DIR"

curl -fSL -o "$DEST_DIR/cl100k_base.tiktoken" \
  https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken

curl -fSL -o "$DEST_DIR/o200k_base.tiktoken" \
  https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken

chmod -R 777 "$DEST_DIR"

echo "Downloaded files to $DEST_DIR:"
ls -l "$DEST_DIR"
