# 我是導演 iamdirector — desktop (open-source edition)

**繁體中文** ｜ [English](#english)

**下載安裝檔 / Download：** [Releases › Latest](https://github.com/tkappletoken/iamdirector/releases/latest)　·　安裝說明 / Install guide：[INSTALL.md](INSTALL.md)

「我是導演」桌面版：寫一段故事，一步一步拍成一支短片——分鏡、生成每一個鏡頭、配音配樂、剪接上字幕、匯出成片。

不用註冊、不用登入就能用。**使用你自己的 AppleToken 金鑰**生成，作品、素材、成片都存在你自己的電腦上。

## 預設接 AppleToken

- 本機模式的生成服務預設是 **AppleToken**（`https://appletoken.app`）。
- 金鑰到 [AppleToken 的「API 憑證」頁](https://appletoken.app/portal/keys) 建立：登入、取個名字、按「建立憑證」。
- **建議為本工具另外建立一把金鑰，並限定可用模型。**
- 金鑰只存在這台電腦的系統加密儲存（macOS 鑰匙圈、Windows DPAPI、Linux Secret Service），畫面只顯示末四碼；只會送到 AppleToken 的 API，不會上傳到其他地方。
- 生成費用從你的 AppleToken 額度扣；每一批送出前都會先報價、等你確認。

## 登入是選用的

登入 [iamdirector.app](https://iamdirector.app) 帳號之後，才多出這些：作品同步到雲端資產庫、一鍵上架到你的頻道、用平台點數付款。不登入也能把成片匯出成檔案，自己上傳。

## 在這台電腦匯出成片

用附帶的 FFmpeg（LGPL 版，沒有 GPL 元件）在本機拼接：

| 平台 | 影片編碼 |
|---|---|
| macOS | 系統內建的 VideoToolbox（H.264） |
| Windows | 系統內建的 Media Foundation（H.264） |
| Linux x64 | 第一次匯出 MP4 時，**經你同意**才從 Cisco 下載 OpenH264（雜湊比對通過才使用）；不同意就匯出 WebM（VP9／Opus）。可在「說明 → H.264 編碼器（OpenH264）…」啟用或停用。*OpenH264 Video Codec provided by Cisco Systems, Inc.* |
| Linux／Windows arm64 | 這一版沒有附 FFmpeg，匯出會停用並說明原因 |

## 從原始碼建置

需要 Node.js 22、Python 3（建置用）、以及各平台編 FFmpeg 的工具（見 `scripts/build-ffmpeg-lgpl*.sh` 開頭）。

```sh
npm ci
npm test
npm run prepare:local -- arm64        # 下載固定雜湊的 Python，放進本機伺服器（依你的架構：arm64／x64）
bash scripts/build-ffmpeg-lgpl.sh arm64   # macOS；Windows 用 build-ffmpeg-lgpl-mingw.sh、Linux 用 build-ffmpeg-lgpl-linux.sh
npm start                              # 開發模式
npm run dist:mac                       # 打包（不簽章）；Windows：npm run dist:win
```

原始碼的下載網址與 SHA-256 都寫死在腳本裡，對不上就停止。

## 授權

- 原始碼：[Apache License 2.0](LICENSE)。
- 「我是導演」「iamdirector」名稱與 logo 保留，不在 Apache-2.0 授權範圍內，見 [TRADEMARKS.md](TRADEMARKS.md)。
- 附帶的第三方軟體與授權：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[NOTICE](NOTICE)。

## 回報安全問題

請不要開公開的 issue，見 [SECURITY.md](SECURITY.md)。

---

<a id="english"></a>
## English

iamdirector desktop turns a short story into a finished video, step by step: storyboard, generate each shot, voice and music, edit and subtitle, export.

No account needed. **Use your own AppleToken API key**; your works, assets and exports stay on your computer.

- **Defaults to AppleToken** (`https://appletoken.app`). Create a key on [AppleToken's API credentials page](https://appletoken.app/portal/keys). **We recommend creating a separate key for this tool and restricting which models it can use.**
- The key is kept only in your OS's encrypted storage (macOS Keychain, Windows DPAPI, Linux Secret Service), is shown only as its last four characters, and is sent only to the AppleToken API.
- Signing in to an iamdirector.app account is optional; it adds the cloud asset library, one-click publishing and paying with platform points.
- On-device export uses a bundled LGPL build of FFmpeg: VideoToolbox on macOS, Media Foundation on Windows; on Linux x64, Cisco's OpenH264 is downloaded only with your consent (otherwise WebM). *OpenH264 Video Codec provided by Cisco Systems, Inc.*
- Build: see the commands above.
- License: Apache-2.0. The names "我是導演" / "iamdirector" and the logo are reserved and not covered by the license ([TRADEMARKS.md](TRADEMARKS.md)).
- Security issues: see [SECURITY.md](SECURITY.md).

Copyright © The iamdirector Authors
