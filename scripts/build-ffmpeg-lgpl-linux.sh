#!/bin/bash
set -euo pipefail
VER=8.1.3
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$ROOT/vendor/.cache"
J=$(nproc)
mkdir -p "$CACHE"

fetch() {
  local f="$CACHE/$1"
  [ -f "$f" ] || curl -sSL --max-time 600 -o "$f" "$2"
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
fetch libvpx-1.15.2.tar.gz https://github.com/webmproject/libvpx/archive/refs/tags/v1.15.2.tar.gz \
  26fcd3db88045dee380e581862a6ef106f49b74b6396ee95c2993a260b4636aa
fetch opus-1.5.2.tar.gz https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz \
  65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1
fetch openh264-2.6.0.tar.gz https://github.com/cisco/openh264/archive/refs/tags/v2.6.0.tar.gz \
  558544ad358283a7ab2930d69a9ceddf913f4a51ee9bf1bfb9e377322af81a69
fetch NotoSansTC-Regular.otf https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/SubsetOTF/TC/NotoSansTC-Regular.otf \
  5bab0cb3c1cf89dde07c4a95a4054b195afbcfe784d69d75c340780712237537

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
DEPS="$WORK/deps"
export PKG_CONFIG_LIBDIR="$DEPS/lib/pkgconfig"
export CFLAGS="-O2 -fPIC" CXXFLAGS="-O2 -fPIC"
for t in freetype-2.13.3.tar.xz fribidi-1.0.16.tar.xz harfbuzz-10.1.0.tar.xz libass-0.17.3.tar.xz ffmpeg-$VER.tar.xz; do
  tar -xJf "$CACHE/$t" -C "$WORK"; done
for t in libvpx-1.15.2.tar.gz opus-1.5.2.tar.gz openh264-2.6.0.tar.gz; do tar -xzf "$CACHE/$t" -C "$WORK"; done

step() { local name=$1; shift; ( "$@" ) > "$WORK/$name.log" 2>&1 || { echo "$name 失敗：" >&2; tail -30 "$WORK/$name.log" >&2; exit 1; }; }

step freetype bash -c "cd '$WORK/freetype-2.13.3' && ./configure --prefix='$DEPS' --enable-static --disable-shared \
  --without-zlib --without-bzip2 --without-png --without-harfbuzz --without-brotli && make -j$J && make install"
step fribidi bash -c "cd '$WORK/fribidi-1.0.16' && ./configure --prefix='$DEPS' --enable-static --disable-shared --disable-docs \
  && make -j$J && make install"
step harfbuzz bash -c "mkdir -p '$WORK/hb' && cd '$WORK/hb' && cmake '$WORK/harfbuzz-10.1.0' -G Ninja \
  -DCMAKE_INSTALL_PREFIX='$DEPS' -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DHB_HAVE_FREETYPE=ON -DHB_HAVE_GLIB=OFF -DHB_HAVE_ICU=OFF -DHB_BUILD_SUBSET=OFF -DCMAKE_PREFIX_PATH='$DEPS' && ninja && ninja install"
cat > "$DEPS/lib/pkgconfig/harfbuzz.pc" <<PC
prefix=$DEPS
libdir=\${prefix}/lib
includedir=\${prefix}/include
Name: harfbuzz
Description: HarfBuzz text shaping library
Version: 10.1.0
Requires.private: freetype2
Libs: -L\${libdir} -lharfbuzz
Libs.private: -lstdc++ -lm
Cflags: -I\${includedir}/harfbuzz
PC
step libass bash -c "cd '$WORK/libass-0.17.3' && ./configure --prefix='$DEPS' --enable-static --disable-shared \
  --disable-fontconfig --disable-require-system-font-provider && make -j$J && make install"
step libvpx bash -c "cd '$WORK/libvpx-1.15.2' && ./configure --prefix='$DEPS' --enable-static --disable-shared --enable-pic \
  --disable-examples --disable-tools --disable-docs --disable-unit-tests --enable-vp9 --disable-vp8-decoder --disable-vp9-decoder \
  && make -j$J && make install"
step opus bash -c "cd '$WORK/opus-1.5.2' && ./configure --prefix='$DEPS' --enable-static --disable-shared --disable-doc \
  --disable-extra-programs && make -j$J && make install"

mkdir -p "$DEPS/include/wels" "$WORK/stub"
cp "$WORK/openh264-2.6.0/codec/api/wels/"*.h "$DEPS/include/wels/"
gcc -O2 -fPIC -shared -Wl,-soname,libopenh264.so.8 -o "$WORK/stub/libopenh264.so.8" "$ROOT/scripts/openh264-stub.c"
ln -sf libopenh264.so.8 "$WORK/stub/libopenh264.so"
cat > "$DEPS/lib/pkgconfig/openh264.pc" <<PC
prefix=$DEPS
Name: openh264
Description: OpenH264 (interface only; the real library is downloaded from Cisco at runtime)
Version: 2.6.0
Libs: -L$WORK/stub -lopenh264
Cflags: -I\${prefix}/include
PC

cd "$WORK/ffmpeg-$VER"
./configure \
  --pkg-config-flags=--static --enable-libass --enable-libvpx --enable-libopus --enable-libopenh264 \
  --prefix="$WORK/install" \
  --disable-autodetect --disable-gpl --disable-nonfree --disable-version3 --enable-pthreads \
  --disable-decoder=libopenh264 --disable-doc --disable-ffplay --disable-network --disable-debug \
  --extra-ldflags="-static-libgcc -static-libstdc++" \
  > "$WORK/configure.log" || { echo "ffmpeg configure 失敗：" >&2; tail -25 ffbuild/config.log >&2; exit 1; }
grep -q "License: LGPL version 2.1 or later" "$WORK/configure.log" \
  || { echo "configure 不是 LGPL 2.1+，停止" >&2; tail -20 "$WORK/configure.log" >&2; exit 1; }
make -j"$J" > "$WORK/make.log" 2>&1 || { tail -30 "$WORK/make.log" >&2; exit 1; }
make install > /dev/null

DEST="$ROOT/vendor/ffmpeg-linux-x64"
rm -rf "$DEST"; mkdir -p "$DEST/fonts"
cp "$WORK/install/bin/ffmpeg" "$WORK/install/bin/ffprobe" "$WORK/stub/libopenh264.so.8" "$DEST/"
patchelf --set-rpath '$ORIGIN' "$DEST/ffmpeg" "$DEST/ffprobe"
readelf -d "$DEST/ffmpeg" | grep -q 'RUNPATH.*\$ORIGIN' || { echo "RUNPATH 沒設上" >&2; exit 1; }
cp "$CACHE/NotoSansTC-Regular.otf" "$DEST/fonts/"
cp COPYING.LGPLv2.1 "$DEST/LICENSE.ffmpeg.txt"
{ echo "FFmpeg $VER (Linux x64), from https://ffmpeg.org/releases/ffmpeg-$VER.tar.xz — LGPL-2.1-or-later."
  echo "Built by scripts/build-ffmpeg-lgpl-linux.sh. Bundled (static): freetype 2.13.3 (FTL), fribidi 1.0.16 (LGPL-2.1),"
  echo "harfbuzz 10.1.0 (MIT), libass 0.17.3 (ISC), libvpx 1.15.2 (BSD-3), opus 1.5.2 (BSD-3)."
  echo "libopenh264.so.8 here is OUR stub (BSD-2, scripts/openh264-stub.c), not Cisco's codec."
  echo "OpenH264 Video Codec provided by Cisco Systems, Inc. is downloaded at runtime only with the user's consent."
  echo "fonts/NotoSansTC-Regular.otf: SIL Open Font License 1.1 (notofonts/noto-cjk Sans2.004)."; } > "$DEST/SOURCE.txt"
BAD=$(ldd "$DEST/ffmpeg" | awk '{print $1}' | grep -vE '^(linux-vdso|libc\.so|libm\.so|libpthread\.so|libdl\.so|librt\.so|/lib64/ld-linux|libopenh264\.so\.8)' || true)
[ -z "$BAD" ] || { echo "ffmpeg 連到非系統函式庫：$BAD" >&2; exit 1; }
ldd "$DEST/ffmpeg" | grep openh264
"$DEST/ffmpeg" -hide_banner -L 2>&1 | head -3
"$DEST/ffmpeg" -hide_banner -encoders 2>/dev/null | grep -E 'libopenh264|libvpx-vp9|libopus'
"$DEST/ffmpeg" -hide_banner -filters 2>/dev/null | grep -E ' subtitles ' || { echo "沒有 subtitles 濾鏡" >&2; exit 1; }
echo "ffmpeg-linux-x64 準備好了：$DEST"
