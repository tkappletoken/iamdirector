#!/bin/bash
set -euo pipefail
VER=8.1.3
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$ROOT/vendor/.cache"
HOST=x86_64-w64-mingw32
J=$(nproc 2>/dev/null || echo 4)
mkdir -p "$CACHE"

fetch() {   # 名稱 網址 雜湊（跟 macOS 版同一組）
  local f="$CACHE/$1"
  [ -f "$f" ] || curl -sSL --max-time 300 -o "$f" "$2"
  [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$3" ] || { echo "雜湊不符，刪掉：$f" >&2; rm -f "$f"; exit 1; }
}
fetch ffmpeg-$VER.tar.xz https://ffmpeg.org/releases/ffmpeg-$VER.tar.xz \
  7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
fetch freetype-2.13.3.tar.xz https://download-mirror.savannah.gnu.org/releases/freetype/freetype-2.13.3.tar.xz \
  0550350666d427c74daeb85d5ac7bb353acba5f76956395995311a9c6f063289
fetch fribidi-1.0.16.tar.xz https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz \
  1b1cde5b235d40479e91be2f0e88a309e3214c8ab470ec8a2744d82a5a9ea05c
fetch harfbuzz-10.1.0.tar.xz https://github.com/harfbuzz/harfbuzz/releases/download/10.1.0/harfbuzz-10.1.0.tar.xz \
  6ce3520f2d089a33cef0fc48321334b8e0b72141f6a763719aaaecd2779ecb82
fetch libass-0.17.3.tar.xz https://github.com/libass/libass/releases/download/0.17.3/libass-0.17.3.tar.xz \
  eae425da50f0015c21f7b3a9c7262a910f0218af469e22e2931462fed3c50959

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
DEPS="$WORK/deps"
export PKG_CONFIG_LIBDIR="$DEPS/lib/pkgconfig"     # 只看自己編的
export CC=$HOST-gcc CXX=$HOST-g++ AR=$HOST-ar RANLIB=$HOST-ranlib
for t in freetype-2.13.3 fribidi-1.0.16 harfbuzz-10.1.0 libass-0.17.3 ffmpeg-$VER; do tar -xJf "$CACHE/$t.tar.xz" -C "$WORK"; done

step() { local name=$1; shift; ( "$@" ) > "$WORK/$name.log" 2>&1 || { echo "$name 失敗：" >&2; tail -30 "$WORK/$name.log" >&2; exit 1; }; }

step freetype bash -c "cd '$WORK/freetype-2.13.3' && ./configure --host=$HOST --prefix='$DEPS' --enable-static --disable-shared \
  --without-zlib --without-bzip2 --without-png --without-harfbuzz --without-brotli && make -j$J && make install"
step fribidi bash -c "cd '$WORK/fribidi-1.0.16' && ./configure --host=$HOST --prefix='$DEPS' --enable-static --disable-shared \
  --disable-docs && make -j$J && make install"
step harfbuzz bash -c "mkdir -p '$WORK/hb' && cd '$WORK/hb' && cmake '$WORK/harfbuzz-10.1.0' -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_C_COMPILER=$HOST-gcc -DCMAKE_CXX_COMPILER=$HOST-g++ -DCMAKE_RC_COMPILER=$HOST-windres \
  -DCMAKE_FIND_ROOT_PATH='$DEPS' -DCMAKE_INSTALL_PREFIX='$DEPS' -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release \
  -DHB_HAVE_FREETYPE=ON -DHB_HAVE_GLIB=OFF -DHB_HAVE_ICU=OFF -DHB_HAVE_GDI=OFF -DHB_HAVE_DIRECTWRITE=OFF -DHB_HAVE_UNISCRIBE=OFF \
  -DHB_BUILD_SUBSET=OFF -DCMAKE_PREFIX_PATH='$DEPS' && ninja && ninja install"
cat > "$DEPS/lib/pkgconfig/harfbuzz.pc" <<PC
prefix=$DEPS
libdir=\${prefix}/lib
includedir=\${prefix}/include
Name: harfbuzz
Description: HarfBuzz text shaping library
Version: 10.1.0
Requires.private: freetype2
Libs: -L\${libdir} -lharfbuzz
Libs.private: -lstdc++ -lpthread
Cflags: -I\${includedir}/harfbuzz
PC
step libass bash -c "cd '$WORK/libass-0.17.3' && ./configure --host=$HOST --prefix='$DEPS' --enable-static --disable-shared \
  --disable-fontconfig --disable-coretext --enable-directwrite --disable-require-system-font-provider --disable-asm \
  && make -j$J && make install"

cd "$WORK/ffmpeg-$VER"
unset CC CXX AR RANLIB
./configure \
  --enable-cross-compile --target-os=mingw32 --arch=x86_64 --cross-prefix=$HOST- --pkg-config=pkg-config \
  --pkg-config-flags=--static --enable-libass \
  --prefix="$WORK/install" \
  --disable-autodetect --disable-gpl --disable-nonfree --disable-version3 \
  --enable-w32threads --enable-mediafoundation --enable-d3d11va \
  --disable-doc --disable-ffplay --disable-network --disable-debug \
  --extra-ldflags="-static -static-libgcc -static-libstdc++" \
  > "$WORK/configure.log" || { echo "ffmpeg configure 失敗：" >&2; tail -25 ffbuild/config.log >&2; exit 1; }
grep -q "License: LGPL version 2.1 or later" "$WORK/configure.log" \
  || { echo "configure 不是 LGPL 2.1+，停止" >&2; tail -20 "$WORK/configure.log" >&2; exit 1; }
make -j"$J" > "$WORK/make.log" 2>&1 || { tail -30 "$WORK/make.log" >&2; exit 1; }
make install > /dev/null

DEST="$ROOT/vendor/ffmpeg-win-x64"
rm -rf "$DEST"; mkdir -p "$DEST"
cp "$WORK/install/bin/ffmpeg.exe" "$WORK/install/bin/ffprobe.exe" "$DEST/"
cp COPYING.LGPLv2.1 "$DEST/LICENSE.ffmpeg.txt"
{ echo "FFmpeg $VER (Windows x64, mingw-w64 cross build), from https://ffmpeg.org/releases/ffmpeg-$VER.tar.xz"
  echo "License: LGPL-2.1-or-later. H.264 via Windows MediaFoundation. Built by scripts/build-ffmpeg-lgpl-mingw.sh."
  echo "Bundled (static): freetype 2.13.3 (FTL), fribidi 1.0.16 (LGPL-2.1), harfbuzz 10.1.0 (MIT), libass 0.17.3 (ISC)."; } > "$DEST/SOURCE.txt"
BAD=$($HOST-objdump -p "$DEST/ffmpeg.exe" | awk '/DLL Name:/{print $3}' | grep -iE '^(lib|.*gcc|.*stdc|.*pthread)' || true)
[ -z "$BAD" ] || { echo "ffmpeg.exe 連到非系統 DLL：$BAD" >&2; exit 1; }
$HOST-objdump -p "$DEST/ffmpeg.exe" | awk '/DLL Name:/{print "  連到", $3}'
grep -q "mediafoundation\|h264_mf" "$WORK/configure.log" || echo "注意：configure 輸出裡沒看到 MediaFoundation" >&2
grep -q " h264_mf" ffbuild/config.mak 2>/dev/null || true
grep -E "CONFIG_H264_MF_ENCODER=yes|CONFIG_SUBTITLES_FILTER=yes|CONFIG_LIBASS=yes" ffbuild/config.mak | sed 's/^/  /'
echo "ffmpeg-win-x64 準備好了：$DEST"
