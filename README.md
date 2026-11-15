# 我是導演 iamdirector — 桌面版下載

[繁體中文](#繁體中文) · [English](#english) · [日本語](#日本語)

**下載最新版 / Download / ダウンロード：** [Releases › Latest](https://github.com/tkappletoken/iamdirector-releases/releases/latest)

這個 repo 只用來發佈安裝檔，不含原始碼。
This repository only hosts installers; it contains no source code.
このリポジトリはインストーラーの配布専用で、ソースコードは含まれていません。

---

## 繁體中文

「我是導演」是 [iamdirector.app](https://iamdirector.app) 的 Mac 桌面版：寫一段故事，拍成一支影片。

### 系統需求
- Apple 晶片的 Mac（M1 以上）。目前沒有 Intel 版。
- macOS 12 Monterey 以上。
- 需要網路連線。

### 下載與安裝
1. 到 [最新版](https://github.com/tkappletoken/iamdirector-releases/releases/latest) 下載 `iamdirector-<版本>-mac-arm64.dmg`。
2. 打開 dmg，把「我是導演」拖進「應用程式」資料夾。
3. 第一次開啟時，macOS 會提醒這是從網路下載的 App，按「打開」即可。
   App 已用 Apple Developer ID（NT IT co., ltd.）簽章並經 Apple 公證。

### 確認檔案完整
每一版的發佈說明都附有 SHA-256。可以在「終端機」執行下面這行，比對結果是否相同：

```sh
shasum -a 256 ~/Downloads/iamdirector-*-mac-arm64.dmg
```

### 更新
目前請到這裡下載新版，覆蓋安裝即可，登入狀態會保留。

---

## English

iamdirector is the Mac desktop app for [iamdirector.app](https://iamdirector.app): write a story, shoot it as a film.

### Requirements
- A Mac with Apple silicon (M1 or later). There is no Intel build yet.
- macOS 12 Monterey or later.
- An internet connection.

### Download and install
1. Download `iamdirector-<version>-mac-arm64.dmg` from the [latest release](https://github.com/tkappletoken/iamdirector-releases/releases/latest).
2. Open the dmg and drag “我是導演” (iamdirector) into the Applications folder.
3. On first launch macOS will note that the app was downloaded from the internet. Click **Open**.
   The app is signed with an Apple Developer ID (NT IT co., ltd.) and notarized by Apple.

### Verify the download
Each release lists the SHA-256 of the dmg. Compare it with the output of:

```sh
shasum -a 256 ~/Downloads/iamdirector-*-mac-arm64.dmg
```

### Updating
For now, download the new version here and install it over the old one. You stay signed in.

---

## 日本語

「我是導演（iamdirector）」は [iamdirector.app](https://iamdirector.app) の Mac デスクトップ版です。ストーリーを書いて、一本の映像に。

### 動作環境
- Apple シリコン搭載の Mac（M1 以降）。Intel 版はまだありません。
- macOS 12 Monterey 以降。
- インターネット接続が必要です。

### ダウンロードとインストール
1. [最新リリース](https://github.com/tkappletoken/iamdirector-releases/releases/latest) から `iamdirector-<バージョン>-mac-arm64.dmg` をダウンロードします。
2. dmg を開き、「我是導演」を「アプリケーション」フォルダにドラッグします。
3. 初回起動時、インターネットからダウンロードしたアプリである旨が表示されたら「開く」をクリックします。
   本アプリは Apple Developer ID（NT IT co., ltd.）で署名され、Apple の公証を受けています。

### ファイルの確認
各リリースには dmg の SHA-256 を記載しています。「ターミナル」で次を実行し、一致するか確認してください。

```sh
shasum -a 256 ~/Downloads/iamdirector-*-mac-arm64.dmg
```

### アップデート
現在は、ここから新しいバージョンをダウンロードして上書きインストールしてください。ログイン状態は保持されます。

---

© NT Technology. All rights reserved.
