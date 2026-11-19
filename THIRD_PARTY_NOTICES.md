# Third-party software bundled with iamdirector desktop

This app bundles the following software as **separate programs** in `Resources/`. They are not
linked into the app itself; you may replace them with your own builds.

## Python (python-build-standalone)
- CPython 3.12.16, build `20261026` from https://github.com/astral-sh/python-build-standalone
- License: Python Software Foundation License (and the licenses of its bundled components,
  listed inside the distribution).

## FFmpeg (LGPL build) — `Resources/ffmpeg/`
- FFmpeg 8.1.3, source: https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz
  (sha256 7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3,
  release signature verified with FFmpeg key FCF9 86EA 15E6 E293 A564 4F10 B432 2F04 D676 58D8)
- License: **LGPL-2.1-or-later** (configured without `--enable-gpl` / `--enable-nonfree`;
  no libx264). Full text: `Resources/ffmpeg/LICENSE.ffmpeg.txt`.
- H.264: macOS uses Apple VideoToolbox; Windows uses Microsoft Media Foundation; Linux uses the
  OpenH264 binary that **Cisco provides and your computer downloads directly from Cisco** only after you
  agree (see "OpenH264" below). On Linux the installer contains only our own placeholder
  `libopenh264.so.8` (`scripts/openh264-stub.c`, no codec inside).
- How it was built: `scripts/build-ffmpeg-lgpl.sh` (macOS), `scripts/build-ffmpeg-lgpl-mingw.sh` (Windows),
  `scripts/build-ffmpeg-lgpl-linux.sh` (Linux) in this repository (details in `Resources/ffmpeg/SOURCE.txt`).
  Statically included libraries:
  - FreeType 2.13.3 — FreeType License (FTL)
  - FriBidi 1.0.16 — LGPL-2.1-or-later
  - HarfBuzz 10.1.0 — MIT
  - libass 0.17.3 — ISC
  - Linux only: libvpx 1.15.2 — BSD-3-Clause; Opus 1.5.2 — BSD-3-Clause
- Linux only: font `Resources/ffmpeg/fonts/NotoSansTC-Regular.otf` (Noto Sans CJK TC, notofonts/noto-cjk
  Sans2.004) — SIL Open Font License 1.1.
- Corresponding source for all of the above: the URLs and hashes in those scripts.
  We will also provide the source on request for three years from distribution.

## Noto Sans TC (fonts) — SIL Open Font License 1.1
- `Resources/local-server/fonts/NotoSansTC-Bold.otf`: Noto Sans TC Bold, Version 2.004 (notofonts/noto-cjk,
  `Sans/SubsetOTF/TC/NotoSansTC-Bold.otf`), subset to common Traditional Chinese characters. Used only to burn
  meme captions into exported videos. © 2014-2021 Adobe. No Reserved Font Name is declared.
- Linux only: `Resources/ffmpeg/fonts/NotoSansTC-Regular.otf` (same project, Sans2.004), used for subtitles.
- License: SIL Open Font License 1.1, full text below (also at `Resources/local-server/fonts/OFL.txt`).

## Electron and npm dependencies
- Electron (MIT) and its bundled components (Chromium etc.): see `LICENSES.chromium.html` inside the app.

## OpenH264 (Linux only, downloaded from Cisco with your consent — not included in the installer)

OpenH264 Video Codec provided by Cisco Systems, Inc.

When you first export an MP4 on Linux, the app asks whether to download Cisco's OpenH264 binary
(version 2.6.0) directly from `https://ciscobinary.openh264.org`. It is used only if its SHA-256 matches
the value pinned in `src/openh264.js`. You can enable, disable or re-enable it at any time from
「說明 → H.264 編碼器（OpenH264）…」. If you decline, exports use WebM (VP9 / Opus) instead.

The following is Cisco's license text for that binary, reproduced in full as Cisco requires
(also in `licenses/OpenH264-BINARY_LICENSE.txt` in the source repository):

```
-------------------------------------------------------
About The Cisco-Provided Binary of OpenH264 Video Codec
-------------------------------------------------------

Cisco provides this program under the terms of the BSD license.  

Additionally, this binary is licensed under Cisco’s AVC/H.264 Patent Portfolio License from MPEG LA, at no cost to you, provided that the requirements and conditions shown below in the AVC/H.264 Patent Portfolio sections are met.  

As with all AVC/H.264 codecs, you may also obtain your own patent license from MPEG LA or from the individual patent owners, or proceed at your own risk.  Your rights from Cisco under the BSD license are not affected by this choice.  

For more information on the OpenH264 binary licensing, please see the OpenH264 FAQ found at http://www.openh264.org/faq.html#binary 

A corresponding source code to this binary program is available under the same BSD terms, which can be found at http://www.openh264.org

-----------
BSD License
-----------

Copyright © 2014 Cisco Systems, Inc.

All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-----------------------------------------
AVC/H.264 Patent Portfolio License Notice
-----------------------------------------

The binary form of this Software is distributed by Cisco under the AVC/H.264 Patent Portfolio License from MPEG LA, and is subject to the following requirements, which may or may not be applicable to your use of this software: 

THIS PRODUCT IS LICENSED UNDER THE AVC PATENT PORTFOLIO LICENSE FOR THE PERSONAL USE OF A CONSUMER OR OTHER USES IN WHICH IT DOES NOT RECEIVE REMUNERATION TO (i) ENCODE VIDEO IN COMPLIANCE WITH THE AVC STANDARD (“AVC VIDEO”) AND/OR (ii) DECODE AVC VIDEO THAT WAS ENCODED BY A CONSUMER ENGAGED IN A PERSONAL ACTIVITY AND/OR WAS OBTAINED FROM A VIDEO PROVIDER LICENSED TO PROVIDE AVC VIDEO.  NO LICENSE IS GRANTED OR SHALL BE IMPLIED FOR ANY OTHER USE.  ADDITIONAL INFORMATION MAY BE OBTAINED FROM MPEG LA, L.L.C. SEE HTTP://WWW.MPEGLA.COM

Accordingly, please be advised that content providers and broadcasters using AVC/H.264 in their service may be required to obtain a separate use license from MPEG LA, referred to as "(b) sublicenses" in the SUMMARY OF AVC/H.264 LICENSE TERMS from MPEG LA found at http://www.openh264.org/mpegla

---------------------------------------------
AVC/H.264 Patent Portfolio License Conditions
---------------------------------------------

In addition, the Cisco-provided binary of this Software is licensed under Cisco's license from MPEG LA only if the following conditions are met:

1. The Cisco-provided binary is separately downloaded to an end user’s device, and not integrated into or combined with third party software prior to being downloaded to the end user’s device;

2. The end user must have the ability to control (e.g., to enable, disable, or re-enable) the use of the Cisco-provided binary;

3. Third party software, in the location where end users can control the use of the Cisco-provided binary, must display the following text:

       "OpenH264 Video Codec provided by Cisco Systems, Inc."

4.  Any third-party software that makes use of the Cisco-provided binary must reproduce all of the above text, as well as this last condition, in the EULA and/or in another location where licensing information is to be presented to the end user.  
 


                          v1.0
```

## SIL Open Font License 1.1 (full text)

```
This Font Software is licensed under the SIL Open Font License,
Version 1.1.

This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL

-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font
creation efforts of academic and linguistic communities, and to
provide a free and open framework in which fonts may be shared and
improved in partnership with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply to
any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software
components as distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to,
deleting, or substituting -- in part or in whole -- any of the
components of the Original Version, by changing formats or by porting
the Font Software to a new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed,
modify, redistribute, and sell modified and unmodified copies of the
Font Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components, in
Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the
corresponding Copyright Holder. This restriction only applies to the
primary font name as presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created using
the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```
