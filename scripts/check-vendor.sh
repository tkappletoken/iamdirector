#!/bin/bash
set -euo pipefail
OS="$1"; ARCH="$2"; WANT_FFMPEG="$3"
V="$(cd "$(dirname "$0")/.." && pwd)/vendor"
fail() { echo "::error::$*"; exit 1; }

PY="$V/python-$ARCH/bin/python3"; [ "$OS" = win ] && PY="$V/python-$ARCH/python.exe"
[ -f "$PY" ] || fail "缺 Python：$PY"
[ -f "$V/local-server/local/studio_local.py" ] || fail "缺本機伺服器"
[ -s "$V/local-server/SOURCE_COMMIT" ] || fail "缺 local-server/SOURCE_COMMIT"
echo "本機伺服器來自 iamdirector $(cat "$V/local-server/SOURCE_COMMIT")"

FF="$V/ffmpeg-$ARCH"
if [ "$WANT_FFMPEG" != true ]; then
  mkdir -p "$FF"; echo "這個架構還沒有附 ffmpeg；本機模式的匯出會停用。" > "$FF/README.txt"
  echo "ffmpeg：這個架構不附"; exit 0
fi
EXE=""; [ "$OS" = win ] && EXE=".exe"
for b in ffmpeg ffprobe; do
  [ -f "$FF/$b$EXE" ] || fail "缺 $FF/$b$EXE"
  [ "$OS" = win ] || chmod +x "$FF/$b"          # artifact 不保留執行權限
done
[ -s "$FF/LICENSE.ffmpeg.txt" ] && [ -s "$FF/SOURCE.txt" ] || fail "ffmpeg 缺授權或來源說明"
if [ "$OS" = linux ]; then
  [ -f "$FF/libopenh264.so.8" ] || fail "缺 OpenH264 空殼"
  grep -q iamdirector_openh264_stub "$FF/libopenh264.so.8" || fail "libopenh264.so.8 不是我們的空殼"
  [ -s "$FF/fonts/NotoSansTC-Regular.otf" ] || fail "缺字幕字型"
fi
if [ "$OS" != win ] && [ "$(uname -s)" = "$( [ "$OS" = mac ] && echo Darwin || echo Linux)" ]; then
  "$FF/ffmpeg" -hide_banner -L 2>&1 | grep -q "Lesser General Public" || \
    { [ "$OS" = mac ] && [ "$ARCH" = x64 ] && [ "$(uname -m)" = arm64 ] && ! arch -x86_64 /usr/bin/true 2>/dev/null; } || \
    fail "ffmpeg 不是 LGPL 版"
fi
echo "ffmpeg：齊全（${OS}-${ARCH}）"
