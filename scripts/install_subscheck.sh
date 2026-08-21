#!/usr/bin/env bash
# 下载 subs-check 二进制（beck-8/subs-check, GPL-3.0，以子进程方式隔离调用）
# 用法: ./scripts/install_subscheck.sh [版本]  默认 latest
set -euo pipefail

VERSION="${1:-latest}"
REPO="beck-8/subs-check"
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$INSTALL_DIR/subs-check"

if [ -x "$BIN" ]; then
    echo "✅ subs-check 已存在: $BIN"
    exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  SUFFIX="linux-amd64" ;;
    aarch64|arm64) SUFFIX="linux-arm64" ;;
    *) echo "❌ 不支持的架构: $ARCH"; exit 1 ;;
esac

if [ "$VERSION" = "latest" ]; then
    URL="https://github.com/${REPO}/releases/latest/download/subs-check-${SUFFIX}.tar.gz"
else
    URL="https://github.com/${REPO}/releases/download/${VERSION}/subs-check-${SUFFIX}.tar.gz"
fi

echo "⬇️  下载 $URL"
TMP="$(mktemp -d)"
curl -fsSL "$URL" | tar -xz -C "$TMP"

FOUND="$(find "$TMP" -type f -name 'subs-check*' | head -1)"
[ -z "$FOUND" ] && { echo "❌ 压缩包中未找到 subs-check"; exit 1; }

mv "$FOUND" "$BIN" && chmod +x "$BIN"
rm -rf "$TMP"
echo "✅ 安装完成: $BIN ($("$BIN" --version 2>/dev/null || echo 'unknown'))"
