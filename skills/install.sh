#!/bin/sh
# dds140-scope スキルを Claude Code と Codex の両方に登録する。
#
#   skills/install.sh           # 登録（Claude は symlink、Codex はコピー）
#   skills/install.sh --check   # 登録状態の確認（中身が一致しているか）
#   skills/install.sh --remove  # 登録を外す
#
# Codex 側はこれまでの ~/.codex/skills の慣習（実ディレクトリ）に合わせて
# コピーする。SKILL.md を直したら、このスクリプトを流し直すこと。
set -eu

NAME=dds140-scope
SRC_DIR=$(cd "$(dirname "$0")/$NAME" && pwd)
CLAUDE_DIR="$HOME/.claude/skills/$NAME"
CODEX_DIR="$HOME/.codex/skills/$NAME"

case "${1:-install}" in
  --check)
    echo "Claude: $CLAUDE_DIR"
    [ -e "$CLAUDE_DIR/SKILL.md" ] && diff -q "$SRC_DIR/SKILL.md" "$CLAUDE_DIR/SKILL.md" \
      && echo "  OK（同一）" || echo "  未登録 または 差異あり"
    echo "Codex:  $CODEX_DIR"
    [ -e "$CODEX_DIR/SKILL.md" ] && diff -q "$SRC_DIR/SKILL.md" "$CODEX_DIR/SKILL.md" \
      && echo "  OK（同一）" || echo "  未登録 または 差異あり"
    ;;
  --remove)
    rm -f "$CLAUDE_DIR" 2>/dev/null || true
    [ -L "$CLAUDE_DIR" ] && rm -f "$CLAUDE_DIR" || true
    rm -rf "$CODEX_DIR"
    echo "外しました"
    ;;
  *)
    mkdir -p "$HOME/.claude/skills" "$HOME/.codex/skills"
    # Claude: symlink（既存の herdr-drover などと同じ方式）
    rm -rf "$CLAUDE_DIR"
    ln -s "$SRC_DIR" "$CLAUDE_DIR"
    # Codex: 実ディレクトリにコピー
    rm -rf "$CODEX_DIR"
    mkdir -p "$CODEX_DIR"
    cp "$SRC_DIR/SKILL.md" "$CODEX_DIR/SKILL.md"
    echo "登録しました:"
    echo "  $CLAUDE_DIR -> $SRC_DIR"
    echo "  $CODEX_DIR (copy)"
    ;;
esac
