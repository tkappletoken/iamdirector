#!/bin/bash
set -euo pipefail
VER=8.1.3
SHA=7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$ROOT/vendor/.cache"
ARCH="${1:-$(uname -m)}"            # arm64 或 x86_64
case "$ARCH" in arm64) OUT_ARCH=arm64 ;; x86_64|x64) ARCH=x86_64; OUT_ARCH=x64 ;; *) echo "不支援 $ARCH" >&2; exit 2 ;; esac
[ "$(uname -s)" = Darwin ] || { echo "只支援 macOS（Windows／Linux 另案）" >&2; exit 2; }

mkdir -p "$CACHE"
fetch() {   # 名稱 網址 雜湊
  local f="$CACHE/$1"
  [ -f "$f" ] || curl -sSL --max-time 300 -o "$f" "$2"
  [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "$3" ] || { echo "雜湊不符，刪掉：$f" >&2; rm -f "$f"; exit 1; }
}
fetch freetype-2.13.3.tar.xz https://download-mirror.savannah.gnu.org/releases/freetype/freetype-2.13.3.tar.xz \
  0550350666d427c74daeb85d5ac7bb353acba5f76956395995311a9c6f063289
fetch fribidi-1.0.16.tar.xz https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz \
  1b1cde5b235d40479e91be2f0e88a309e3214c8ab470ec8a2744d82a5a9ea05c
fetch harfbuzz-10.1.0.tar.xz https://github.com/harfbuzz/harfbuzz/releases/download/10.1.0/harfbuzz-10.1.0.tar.xz \
  6ce3520f2d089a33cef0fc48321334b8e0b72141f6a763719aaaecd2779ecb82
fetch libass-0.17.3.tar.xz https://github.com/libass/libass/releases/download/0.17.3/libass-0.17.3.tar.xz \
  eae425da50f0015c21f7b3a9c7262a910f0218af469e22e2931462fed3c50959
TAR="$CACHE/ffmpeg-$VER.tar.xz"
[ -f "$TAR" ] || curl -sSL -o "$TAR" "https://ffmpeg.org/releases/ffmpeg-$VER.tar.xz"
GOT=$(shasum -a 256 "$TAR" | cut -d' ' -f1)
[ "$GOT" = "$SHA" ] || { echo "雜湊不符，刪掉：$TAR" >&2; rm -f "$TAR"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
DEPS="$WORK/deps"
export CC="clang -arch $ARCH" CFLAGS="-mmacosx-version-min=12.0 -O2" CXXFLAGS="-mmacosx-version-min=12.0 -O2"
export PKG_CONFIG_LIBDIR="$DEPS/lib/pkgconfig"    # 只看我們自己編的，不看 Homebrew 的
HOSTF="--host=$([ "$ARCH" = arm64 ] && echo aarch64 || echo x86_64)-apple-darwin"
J=$(sysctl -n hw.ncpu)
for t in freetype-2.13.3 fribidi-1.0.16 harfbuzz-10.1.0 libass-0.17.3; do tar -xJf "$CACHE/$t.tar.xz" -C "$WORK"; done
( cd "$WORK/freetype-2.13.3" && ./configure --prefix="$DEPS" $HOSTF --enable-static --disable-shared \
    --without-zlib --without-bzip2 --without-png --without-harfbuzz --without-brotli && make -j"$J" && make install ) > "$WORK/freetype.log" 2>&1 \
  || { tail -20 "$WORK/freetype.log" >&2; exit 1; }
( cd "$WORK/fribidi-1.0.16" && ./configure --prefix="$DEPS" $HOSTF --enable-static --disable-shared --disable-docs \
    && make -j"$J" && make install ) > "$WORK/fribidi.log" 2>&1 || { tail -20 "$WORK/fribidi.log" >&2; exit 1; }
( mkdir -p "$WORK/hb" && cd "$WORK/hb" && cmake "$WORK/harfbuzz-10.1.0" -G Ninja -DCMAKE_INSTALL_PREFIX="$DEPS" \
    -DCMAKE_OSX_ARCHITECTURES="$ARCH" -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release \
    -DHB_HAVE_FREETYPE=ON -DHB_HAVE_GLIB=OFF -DHB_HAVE_ICU=OFF -DHB_HAVE_CORETEXT=OFF -DHB_BUILD_SUBSET=OFF \
    -DCMAKE_PREFIX_PATH="$DEPS" && ninja && ninja install ) > "$WORK/harfbuzz.log" 2>&1 || { tail -20 "$WORK/harfbuzz.log" >&2; exit 1; }
cat > "$DEPS/lib/pkgconfig/harfbuzz.pc" <<PC
prefix=$DEPS
libdir=\${prefix}/lib
includedir=\${prefix}/include
Name: harfbuzz
Description: HarfBuzz text shaping library
Version: 10.1.0
Requires.private: freetype2
Libs: -L\${libdir} -lharfbuzz
Libs.private: -lc++
Cflags: -I\${includedir}/harfbuzz
PC
( cd "$WORK/libass-0.17.3" && ./configure --prefix="$DEPS" $HOSTF --enable-static --disable-shared \
    --disable-fontconfig --enable-coretext --disable-require-system-font-provider --disable-asm \
    && make -j"$J" && make install ) > "$WORK/libass.log" 2>&1 || { tail -20 "$WORK/libass.log" >&2; exit 1; }

tar -xJf "$TAR" -C "$WORK"
cd "$WORK/ffmpeg-$VER"
unset CC CFLAGS CXXFLAGS
CROSS=""
if [ "$ARCH" != "$(uname -m)" ]; then CROSS="--enable-cross-compile --target-os=darwin"; fi   # 在 arm64 機器上編 x86_64
./configure $CROSS \
  --pkg-config-flags=--static --enable-libass \
  --prefix="$WORK/install" --arch="$ARCH" --cc="clang -arch $ARCH" \
  --disable-autodetect --disable-gpl --disable-nonfree --disable-version3 \
  --enable-videotoolbox --enable-audiotoolbox --enable-zlib \
  --disable-doc --disable-ffplay --disable-network --disable-debug \
  --enable-pic --extra-cflags="-mmacosx-version-min=12.0" --extra-ldflags="-mmacosx-version-min=12.0" \
  > "$WORK/configure.log" || { echo "ffmpeg configure 失敗：" >&2; tail -25 ffbuild/config.log >&2; exit 1; }
grep -q "License: LGPL version 2.1 or later" "$WORK/configure.log" \
  || { echo "configure 不是 LGPL 2.1+，停止" >&2; tail -20 "$WORK/configure.log" >&2; exit 1; }
make -j"$(sysctl -n hw.ncpu)" > "$WORK/make.log" 2>&1 || { tail -30 "$WORK/make.log" >&2; exit 1; }
make install > /dev/null

DEST="$ROOT/vendor/ffmpeg-$OUT_ARCH"
rm -rf "$DEST"; mkdir -p "$DEST"
cp "$WORK/install/bin/ffmpeg" "$WORK/install/bin/ffprobe" "$DEST/"
cp COPYING.LGPLv2.1 "$DEST/LICENSE.ffmpeg.txt"
{ echo "FFmpeg $VER, built from https://ffmpeg.org/releases/ffmpeg-$VER.tar.xz (sha256 $SHA)";
  echo "License: LGPL-2.1-or-later. Source code: same URL. Configure:";
  grep -m1 '^  configuration:' <("$DEST/ffmpeg" -hide_banner -buildconf 2>&1) || "$DEST/ffmpeg" -hide_banner -buildconf 2>&1 | head -3; } > "$DEST/SOURCE.txt"
if otool -L "$DEST/ffmpeg" | tail -n +2 | grep -vE '^\s*(/usr/lib/|/System/Library/)'; then
  echo "ffmpeg 連到了非系統的函式庫，停止" >&2; exit 1
fi
"$DEST/ffmpeg" -hide_banner -L 2>&1 | head -3
"$DEST/ffmpeg" -hide_banner -encoders 2>/dev/null | grep -E 'h264_videotoolbox| aac '
"$DEST/ffmpeg" -hide_banner -filters 2>/dev/null | grep -E ' subtitles ' || { echo "沒有 subtitles 濾鏡（libass 沒編進去），停止" >&2; exit 1; }
for f in COPYING; do :; done
{ echo; echo "Bundled into ffmpeg (static): freetype 2.13.3 (FTL), fribidi 1.0.16 (LGPL-2.1), harfbuzz 10.1.0 (MIT), libass 0.17.3 (ISC)."; } >> "$DEST/SOURCE.txt"
echo "ffmpeg-$OUT_ARCH 準備好了：$DEST"
