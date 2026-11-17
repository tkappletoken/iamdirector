# 我是導演 iamdirector — 桌面版下載

[繁體中文](#繁體中文) · [English](#english) · [日本語](#日本語)

**下載最新版 / Download / ダウンロード：** [Releases › Latest](https://github.com/tkappletoken/iamdirector/releases/latest)

這個 repo 只用來發佈安裝檔，不含原始碼。
This repository only hosts installers; it contains no source code.
このリポジトリはインストーラーの配布専用で、ソースコードは含まれていません。

---

## 繁體中文

「我是導演」是 [iamdirector.app](https://iamdirector.app) 的桌面版：寫一段故事，拍成一支影片。需要網路連線。

### 下載哪一個

| 電腦 | 檔案 |
|---|---|
| Mac（Apple 晶片，M1 以上） | `iamdirector-<版本>-mac-arm64.dmg` |
| Mac（Intel） | `iamdirector-<版本>-mac-x64.dmg` |
| Windows（一般電腦） | `iamdirector-<版本>-win-x64.exe` |
| Windows（ARM，例如 Snapdragon） | `iamdirector-<版本>-win-arm64.exe` |
| Linux x64 | `iamdirector-<版本>-linux-x86_64.AppImage` 或 `…-linux-amd64.deb` |
| Linux ARM | `iamdirector-<版本>-linux-arm64.AppImage` 或 `…-linux-arm64.deb` |

不知道自己的 Mac 是哪一種：左上角  →「關於這台 Mac」，「晶片」寫 Apple M 開頭就選 arm64，寫 Intel 就選 x64。

### Mac
1. 打開 dmg，把「我是導演」拖進「應用程式」。
2. 第一次開啟時 macOS 會提醒這是從網路下載的 App，按「打開」。App 已用 Apple Developer ID 簽章並經 Apple 公證。
3. 需要 macOS 12 以上。

### Windows
⚠ **Windows 版目前沒有程式碼簽章**。第一次執行安裝檔時會出現「**Windows 已保護您的電腦**」，這不是病毒警告：
1. 按「**其他資訊**」。
2. 確認應用程式名稱是 `iamdirector-<版本>-win-….exe`，再按「**仍要執行**」。
3. 依照安裝程式完成安裝。

需要 Windows 10 或 11（64 位元）。

### Linux
- **AppImage**：下載後在終端機執行 `chmod +x iamdirector-*.AppImage`，再執行它。部分發行版需要先安裝 `libfuse2`。
- **deb**（Ubuntu、Debian）：`sudo apt install ./iamdirector-*.deb`
- 建議 Ubuntu 22.04 以上或同等的發行版。

### 確認檔案完整
每一版的發佈說明都列出所有檔案的 SHA-256。
- Mac／Linux：`shasum -a 256 <檔案>`（Linux 也可以用 `sha256sum <檔案>`）
- Windows（PowerShell）：`Get-FileHash <檔案> -Algorithm SHA256`

### 自動更新
- **0.1.5 起會自動更新**：app 會自動檢查新版本。小改版在背景下載，完成後詢問是否重新啟動；較大的改版會先詢問是否下載。可在「說明」選單關閉「結束時自動安裝更新」。
- **0.1.4 以前的版本**沒有自動更新，請到這裡手動下載安裝一次，之後就會自動更新。覆蓋安裝即可，登入狀態會保留。
- **Linux deb 版**不會自動更新，請改用 AppImage。
- **Mac 要放在「應用程式」裡才能自動更新**：直接在 dmg 或「下載項目」裡開啟時，macOS 不允許 app 更新自己。0.1.7 起遇到這種情況會提醒一次，並提供「幫我移過去」按鈕。

---

## English

iamdirector is the desktop app for [iamdirector.app](https://iamdirector.app): write a story, shoot it as a film. An internet connection is required.

### Which file

| Computer | File |
|---|---|
| Mac (Apple silicon, M1 or later) | `iamdirector-<version>-mac-arm64.dmg` |
| Mac (Intel) | `iamdirector-<version>-mac-x64.dmg` |
| Windows (most PCs) | `iamdirector-<version>-win-x64.exe` |
| Windows (ARM, e.g. Snapdragon) | `iamdirector-<version>-win-arm64.exe` |
| Linux x64 | `iamdirector-<version>-linux-x86_64.AppImage` or `…-linux-amd64.deb` |
| Linux ARM | `iamdirector-<version>-linux-arm64.AppImage` or `…-linux-arm64.deb` |

Not sure which Mac you have?  menu → **About This Mac**: if “Chip” starts with Apple M, pick arm64; if it says Intel, pick x64.

### Mac
1. Open the dmg and drag “我是導演” (iamdirector) into Applications.
2. On first launch, macOS notes the app was downloaded from the internet. Click **Open**. The app is signed with an Apple Developer ID and notarized by Apple.
3. Requires macOS 12 or later.

### Windows
⚠ **The Windows build is not code-signed yet.** When you first run the installer, Windows shows “**Windows protected your PC**”. This is not a virus warning:
1. Click **More info**.
2. Check that the app name is `iamdirector-<version>-win-….exe`, then click **Run anyway**.
3. Follow the installer.

Requires Windows 10 or 11 (64-bit).

### Linux
- **AppImage**: run `chmod +x iamdirector-*.AppImage`, then run the file. Some distributions need `libfuse2` installed first.
- **deb** (Ubuntu, Debian): `sudo apt install ./iamdirector-*.deb`
- Ubuntu 22.04 or later (or an equivalent distribution) is recommended.

### Verify the download
Each release lists the SHA-256 of every file.
- Mac / Linux: `shasum -a 256 <file>` (or `sha256sum <file>` on Linux)
- Windows (PowerShell): `Get-FileHash <file> -Algorithm SHA256`

### Automatic updates
- **From 0.1.5 on, the app updates itself.** It checks for new versions automatically. Minor updates download in the background and you are asked before restarting; larger updates ask before downloading. To turn this off, uncheck “結束時自動安裝更新” (install updates when quitting) in the “說明” (Help) menu.
- **Versions 0.1.4 and earlier** cannot update themselves. Download and install a new version here once; later versions arrive automatically. Install over the old one; you stay signed in.
- **The Linux deb package** does not update automatically. Use the AppImage instead.
- **On a Mac, the app must be in Applications to update itself.** If you open it directly from the dmg or the Downloads folder, macOS does not let it update. From 0.1.7, the app tells you once and offers a button to move it for you.

---

## 日本語

「我是導演（iamdirector）」は [iamdirector.app](https://iamdirector.app) のデスクトップ版です。ストーリーを書いて、一本の映像に。インターネット接続が必要です。

### どれをダウンロードするか

| パソコン | ファイル |
|---|---|
| Mac（Apple シリコン、M1 以降） | `iamdirector-<バージョン>-mac-arm64.dmg` |
| Mac（Intel） | `iamdirector-<バージョン>-mac-x64.dmg` |
| Windows（一般的な PC） | `iamdirector-<バージョン>-win-x64.exe` |
| Windows（ARM、Snapdragon など） | `iamdirector-<バージョン>-win-arm64.exe` |
| Linux x64 | `iamdirector-<バージョン>-linux-x86_64.AppImage` または `…-linux-amd64.deb` |
| Linux ARM | `iamdirector-<バージョン>-linux-arm64.AppImage` または `…-linux-arm64.deb` |

Mac の種類がわからない場合：  メニュー →「この Mac について」で「チップ」が Apple M で始まれば arm64、Intel なら x64 を選んでください。

### Mac
1. dmg を開き、「我是導演」を「アプリケーション」フォルダにドラッグします。
2. 初回起動時、インターネットからダウンロードしたアプリである旨が表示されたら「開く」をクリックします。本アプリは Apple Developer IDで署名され、Apple の公証を受けています。
3. macOS 12 以降が必要です。

### Windows
⚠ **Windows 版は現在コード署名されていません。** インストーラーを初めて実行すると「**Windows によって PC が保護されました**」と表示されます。ウイルスの警告ではありません。
1. 「**詳細情報**」をクリックします。
2. アプリ名が `iamdirector-<バージョン>-win-….exe` であることを確認し、「**実行**」をクリックします。
3. インストーラーの指示に従ってインストールします。

Windows 10 または 11（64 ビット）が必要です。

### Linux
- **AppImage**：`chmod +x iamdirector-*.AppImage` を実行してから、ファイルを実行します。ディストリビューションによっては先に `libfuse2` のインストールが必要です。
- **deb**（Ubuntu・Debian）：`sudo apt install ./iamdirector-*.deb`
- Ubuntu 22.04 以降（または同等のディストリビューション）を推奨します。

### ファイルの確認
各リリースにすべてのファイルの SHA-256 を記載しています。
- Mac／Linux：`shasum -a 256 <ファイル>`（Linux では `sha256sum <ファイル>` も可）
- Windows（PowerShell）：`Get-FileHash <ファイル> -Algorithm SHA256`

### 自動アップデート
- **0.1.5 以降は自動でアップデートされます。** 新しいバージョンを自動で確認し、小さな更新はバックグラウンドでダウンロードして再起動の前に確認します。大きな更新はダウンロードの前に確認します。「說明」（ヘルプ）メニューの「結束時自動安裝更新」（終了時にアップデートをインストール）でオフにできます。
- **0.1.4 以前のバージョン**は自動アップデートできません。ここから一度手動でダウンロードしてインストールしてください。以降は自動で更新されます。上書きインストールでログイン状態は保持されます。
- **Linux の deb 版**は自動アップデートされません。AppImage をご利用ください。
- **Mac では「アプリケーション」フォルダに入れないと自動アップデートされません。** dmg や「ダウンロード」フォルダから直接開くと、macOS はアプリの自己更新を許可しません。0.1.7 以降はその場合に一度お知らせし、移動するボタンを表示します。

---

© The iamdirector Authors. Source code licensed under Apache-2.0; see LICENSE.
