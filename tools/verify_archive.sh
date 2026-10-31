#!/bin/sh
# vendor/ に保全した配布物のハッシュを検証する。
#   tools/verify_archive.sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f vendor/SHA256SUMS ]; then
  echo "vendor/SHA256SUMS がありません（vendor/ は Git 管理外）" >&2
  exit 1
fi
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 -c vendor/SHA256SUMS
else
  sha256sum -c vendor/SHA256SUMS
fi
