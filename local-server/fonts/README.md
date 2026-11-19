# fonts/

| 檔案 | 用途 |
|---|---|
| `NotoSansTC-Bold.otf` | 迷因字卡（匯出時燒進畫面）的唯一字型：Noto Sans TC Bold，繁中常用字子集 |
| `OFL.txt` | SIL Open Font License 1.1 全文 |

## 來源與授權

- 字型：Noto Sans TC Bold，Version 2.004，Google／Adobe 的 Noto CJK 專案。
  來源 <https://github.com/notofonts/noto-cjk>（`Sans/SubsetOTF/TC/NotoSansTC-Bold.otf`）。
- 版權：© 2014-2021 Adobe（字型 name table 的 ID 0）。
- 授權：SIL Open Font License 1.1（`OFL.txt`）。OFL 允許跟軟體一起散佈、也允許修改（這裡做了子集，算修改版）；
  條件是授權全文跟著走、字型不單獨販售。這份字型的版權聲明沒有列保留字型名稱（Reserved Font Name），
  所以子集沿用「Noto Sans TC」這個名字可以。桌面版開源（export-oss）會把這個資料夾連同 `OFL.txt` 一起帶到公開 repo。
- 子集：只收 Big5 第一級＋第二級常用字、中文標點、注音、ASCII 與全形字（約 1.4 萬字，4.1MB；完整版 5.8MB）。
  重做方法見 `scripts/subset_font.py`（開發時才需要 fonttools）。

## 誰在用、怎麼找到

- `export_lambda/render.py` 燒迷因字卡時一律用 `subtitles=…:fontsdir=<這個資料夾>`，ASS 的 Fontname 是 `Noto Sans TC`。
  **不靠系統字型**：桌面版 mac 寫 PingFang TC 會打不開、Linux 版沒有任何字型來源。
- 找不到這個檔、或字卡裡有字型沒有的字 → 匯出直接失敗並說明原因，不會靜默改用別的字型。
- 本機模式：`local/studio_local.py` 把 `<repo 根目錄>/fonts` 傳給 render（`caption_fontsdir`）。桌面版打包要把這個資料夾
  放進 SERVER_FILES、保持同樣的相對位置。
- 網頁版（Lambda）：字型 layer 的 `/opt/fonts` 要放這一份（見 `export_lambda/DEPLOY.md`），或設 `CAPTION_FONTS_DIR`。
