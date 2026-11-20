# iamdirector 桌面版：開源開發者指南

這份文件寫給想讀、改、或接上自己 Agent 的開發者。內容照目前的程式寫；跟程式對不上時以程式為準，歡迎發 issue。

## 1. 架構概覽

桌面版是一個 Electron 殼，包著一支**只綁 127.0.0.1 的本機 Python 伺服器**（`local-server/local/studio_local.py`）。
畫面是 `ui2.html`（工作台），伺服器負責專案、素材、報價、送件、匯出。生成本身打 AppleToken 的公開 API（`/v2`），
**用的是使用者自己的金鑰**，不經過任何其他伺服器。

    ┌────────── Electron（桌面殼）──────────┐
    │  視窗：ui2.html（工作台）                │
    │  系統鑰匙圈：保管使用者的 AppleToken 金鑰  │
    └──────────────┬──────────────────────┘
                   │ stdin／stdout（JSON 一行一則）＋ http://127.0.0.1:<port>
    ┌──────────────▼──────────────────────┐
    │ local-server/local/studio_local.py        │
    │   SQLite（local-server/local/sqlite_store.py）│──→ AppleToken /v2（使用者自己的金鑰）
    │   /api/*（工作台用）、/mcp（給 Agent）     │
    │   ffmpeg（匯出、取格、接縫量測）           │
    └──────────────────────────────────────┘

主要的資料夾：

| 路徑 | 做什麼 |
|---|---|
| `local-server/local/studio_local.py` | 本機伺服器：路由、身分（人／Agent）、核准卡、匯出、各項開關 |
| `local-server/local/sqlite_store.py` | 把共用的 SQL（PostgreSQL 寫法）在游標層翻成 SQLite |
| `local-server/local/agent_exec.py` | Filming Agent 主迴圈的本機執行端（第 5 節） |
| `local-server/filming/` | Agent 的純邏輯：主迴圈狀態機（`agent_loop.py`）、長片規劃（`long_plan.py`）、品管報告形狀（`qc_report.py`）、導演控制（`dir_controls.py`）、灰模（`blockout*.py`）、介面描述檔（`ui_schema.py`）…只用標準庫 |
| `local-server/export_lambda/postblocks/` | 後製積木（匯出管線）：每一塊一支檔，`catalog()` 列出積木與參數 |
| `local-server/cli/appletoken/` | CLI 與 MCP 工具表（`mcp/tools.py`）；本機的 `/mcp` 直接用這一份 |
| `local-server/` 底下的 `upstream.py`、`studio_store.py`、`approvals.py`、`takes.py`、`qc.py`、`storyboard.py`… | 本機伺服器共用的模組（上游也拿它們跑網頁版） |

設計原則（每個新功能都照這幾條）：

* **新舊並存、開關預設關**：新功能放在開關後面，壞了自動退回原本的行為，舊的程式不刪。
* **Agent 直接動手，安全網是回得去**：介面、分鏡這類不花錢的東西，Agent 寫了就生效；能回預設、能還原上一步。
* **錢一律受上限約束**：會花錢的事情走核准卡與使用者自己設的單支／每日上限（第 4 節）。
* **只用標準庫**：桌面版附的 Python 沒有第三方套件；`local-server/` 底下的程式都只准 import 標準庫（`npm run prepare:local` 會用附的 Python 實際 import 一次）。

## 2. 本機伺服器怎麼跑

整個 App 怎麼從原始碼建起來，先看 README 的「從原始碼建置」：

    npm ci
    npm test
    npm run prepare:local -- arm64     # 下載固定雜湊的 Python，放進本機伺服器（依你的架構：arm64／x64）
    npm start                          # 開發模式：桌面殼會自己起本機伺服器

想單獨跑本機伺服器（例如接自己的 Agent、或只改後端）：需要 Python 3.10 以上（只用標準庫）、ffmpeg（匯出與取格要用；沒有的話相關功能會回清楚的錯誤）、一把 AppleToken 金鑰。

    python3 -I local-server/local/studio_local.py --data-dir <資料夾> [--port 0] [--ffmpeg-dir <ffmpeg 所在目錄>]

* `--data-dir`：SQLite、素材原檔、各項開關的設定檔、Agent 的連線檔都放這裡。
* `--port 0`：由系統挑一個 port；開好之後 stdout 會印一行 `{"ready": true, "port": N}`。
* `--gateway-base`：AppleToken API 位址，預設 `https://appletoken.app/v2`。只收 https，或 `http://127.0.0.1`（自己架的假上游，開發用）。

伺服器啟動後**從 stdin 等一行 init**（桌面殼會送；單獨跑時自己貼一行）：

    {"op": "init", "token": "<至少 32 字元的隨機字串>", "key": "<你的 AppleToken 金鑰，可省略>"}

* `token`：之後**每個** HTTP 請求都要帶 `X-Local-Token: <token>`（連首頁也是），這是「人」的身分。
* `key`：只放記憶體，不寫檔、不進 log；畫面上貼的新金鑰驗證過後，伺服器會經 stdout 送 `{"op": "store_key", …}`
  請桌面殼放進系統鑰匙圈。單獨跑時沒有桌面殼，請一律用 init 的 `key` 帶金鑰。
* stdin 關掉（桌面殼結束）伺服器就跟著結束。

安全邊界：只綁 127.0.0.1；Host 只收 `127.0.0.1:N`／`localhost:N`（擋 DNS rebinding）；有 Origin 就必須是自己。

## 3. 兩種身分與 MCP

| 身分 | 怎麼帶 | 能做什麼 |
|---|---|---|
| 人 | `X-Local-Token`（init 給的 token） | 全部，包括核准卡、設上限、切開關、換金鑰 |
| Agent | `/mcp`，`Authorization: Bearer iadl_…`（連線檔裡的 token） | 報價、讀取、建作品、送出**已核准**的卡、後製、take、主迴圈…（`AGENT_ALLOWED` 白名單）；核准、改上限、切開關、換金鑰一律 403 |

**Agent 的連線檔**：`<data-dir>/mcp.json`（權限 0600），內容是 `{"url": "http://127.0.0.1:<port>/mcp", "token": "iadl_…"}`。
把它設定給你的 MCP 用戶端（例如 Claude Code）就能連上。人可以在 App 裡重新產生權杖（舊的立刻失效）。

`/mcp` 是 Streamable HTTP、JSON-RPC 2.0、只回 `application/json`，支援 `initialize`、`ping`、`tools/list`、`tools/call`。
**實際可用的工具以 `tools/list` 為準**（每一版會增減）；下面依用途分組列出（標 💰 的會花錢，受第 4 節的閘門管）：

* **導演工作流入口**：`director_plan`（先呼叫這一支，回步驟與工作台狀態）、`workbench_health`、`workbench_capabilities`
* **作品與專案**：`create_work`、`work_get`、`work_clone`、`quote_work`、`list_projects`、`project_create`、`project_rename`、`project_add_item`、`project_remove_item`、`store_get`、`store_put`
* **分鏡與導演控制**：`parse_shots`、`build_captions`、`storyboard_ai_quote`、`storyboard_ai`💰、`storyboard_quote`、`shots_confirm`💰、`dirctl_catalog`、`dirctl_compose`、`shot_dirctl_set`、`previs_rig`
* **報價、核准卡、送件**：`estimate`、`quote`、`video_quote`、`request_approval`、`status`、`submit_approved`💰、`video_confirm`💰、`video_confirm_status`、`video_status`、`video_wait`、`video_archive_status`、`agent_pending_status`、`result`、`model_caps`
* **圖片、素材、角色**：`image_generate`💰、`image_outpaint`💰、`character_angles`💰、`list_assets`、`asset_upload`、`asset_update`、`check_asset`、`check_refs`
* **聲音**：`audio_speech_quote`、`audio_music_quote`、`audio_confirm`💰、`audio_music_status`、`post_process`💰、`post_process_status`、`post_process_wait`
* **品管**：`video_qc`💰、`qc_rate`💰、`qc_rating`
* **每鏡候選與長片接力**：`take_list`、`take_add`、`take_update`、`take_qc`、`take_pick`、`take_retake_plan`、`chain_create`、`chain_next`、`chain_update`
* **Filming Agent 主迴圈**（第 5 節）：`agent_plan`、`agent_run`💰、`agent_answer`💰
* **後製積木與匯出**：`blocks_list`、`pipeline_from_template`、`pipeline_validate`、`pipeline_preview`、`pipeline_export`、`twist_detect`、`meme_export`、`timeline_place`、`timeline_trim`、`export_request`
* **介面描述檔**（Agent 直接組你的介面、隨時回預設或還原）：`ui_actions_list`、`ui_get`、`ui_compose`、`ui_edit`、`ui_preview`、`ui_save`、`ui_apply`、`ui_reset`、`ui_undo`、`ui_onboarding_status`
* **帳戶與用量**：`list_models`、`get_balance`、`list_usage`、`payer_state`
* **取檔網址**：`video_download_url`、`post_process_download_url`、`asset_download_url`、`audio_music_download_url`
* **網頁版才有的功能**（本機呼叫會回 501＋說明；清單在 `local-server/local/studio_local.py` 的 `MISSING`，工作台頁面的 `window.__STUDIO__.missing` 也看得到）：`wallet_*`、`youtube_*`、`pitch_*`

## 4. 錢：核准卡、上限、Agent 直送

所有花錢的動作都先**報價**、再**送出**；Agent 報價時一律建一張**核准卡**：

1. **預先授權**（預設關）：使用者在 App 裡設好單支與每日上限、打開預先授權，Agent 的卡在上限內就自動核准。
2. **Agent 直送**（`mcp_direct.json`，預設關）：打開時 Agent 的卡在上限內當場核准、直接送；**沒設上限回 409、超過回 402**，
   卡片標成 rejected、不留著等人。改上限或關掉直送，還沒送出的直送卡一律收回。
3. 兩個都沒開：卡片 pending，等人在 App 裡核准，Agent 再 `submit_approved`。

上限只有人能改（`/api/approvals/limits` 不在 Agent 白名單）。每日上限是加總當天已核准、已送出的卡算的。

## 5. Filming Agent 主迴圈

一句需求（加上可省略的分鏡）→ 規劃（分段、首幀來源、接縫、成本）→ 逐鏡生成 → 品管 → 不合格只重做那一鏡 → 交片。
狀態機是純函式（`local-server/filming/agent_loop.py`），本機的執行端在 `local-server/local/agent_exec.py`，狀態存在 `<data-dir>/agent_runs/<run>.json`。

**端點**（都要主迴圈的開關打開，關著回 501）：

| 端點 | 做什麼 |
|---|---|
| `POST /api/local/agent/plan` | 只規劃，不存 run、不花錢 |
| `POST /api/local/agent/start` | 開拍：`{request, input?, storyboard?, cast?, caps?, model, aspect_ratio?, resolution?, project_id?, budget?, max_retakes?, target_seconds?}` |
| `POST /api/local/agent/step` | 往下跑一步：`{run, decision? \| event?}`；每一步最多輪詢一次就回應，呼叫端再 step |
| `GET /api/local/agent/get?run=` | 整份狀態 |
| `GET /api/local/agent/runs` | 最近的 run |

**主迴圈發出的動作**（回應裡的 `do`）：

| do | 意思 | 呼叫端要做什麼 |
|---|---|---|
| `generate` | 送這一鏡（執行端會建核准卡、送件） | 再 `step` |
| `wait_refund` | 生成失敗，等確認錢退了才重做 | 再 `step` |
| `check` | 這一鏡要品管 | 自動驗片開著會自己做；否則自己看片，回 `event: {type: "checked", reports}` |
| `wait_blockout` | 灰模還在背景渲染 | 過一會兒再 `step` |
| `ask` | 停下來問人（`pause.reason`、`options`） | 照 options 回 `decision`，或處理好（例如在 App 核准卡片）再 `resume` |
| `deliver`／`done`／`stopped` | 交片／結束 | — |

**ask 的原因**：`controls_gap`（分鏡缺必填，回 `event: {type: "controls", storyboard, cast?}` 補）、`plan_over_budget`、`retakes_exhausted`、
`card_pending`（卡片等人核准）、`over_limit`（Agent 直送被上限擋下，人調高上限後 `resume`）、`repriced`（重新報價漲價了）、
`no_price`、`over_per_job`、`over_per_run`、`approval_needed`。

**呼叫端能送的**：`decision` 是 `resume`、`stop`、`accept_best`（`approve`、`raise` 只有人能用，Agent 送會被拒）；
`event.type` 是 `checked`、`interrupt`、`controls`。其他結果只由執行端產生。

**回應的 `notes`** 會說出沒做到或退回的事，例如 `first_frame`（首幀接力沒開）、`frame_relay:fallback:<原因>`、`agent_qc:<原因>`、
`controls:<提醒>`、`lock_qc_unavailable`，不會靜默略過。

## 6. 開關一覽

每個開關都是**本機設定檔優先，沒設看環境變數，再沒有就是預設**；設定檔在 `<data-dir>/`，只有人能切（Agent 打 POST 一律 403）。

| 開關 | 設定檔 | 環境變數 | 預設 | 切換的端點 | 打開之後 |
|---|---|---|---|---|---|
| 主迴圈 | `agent_loop.json` | `STUDIO_LOCAL_AGENT_LOOP` | off | `/api/local/agent-loop` | 主迴圈端點與 `agent_*` 工具可以用 |
| Agent 範圍 | `agent_scope.json` | `STUDIO_LOCAL_AGENT_SCOPE` | basic | `/api/local/agent-scope` | `full`：Agent 也能做分鏡、配音、生圖、驗片 |
| Agent 直送 | `mcp_direct.json` | `STUDIO_LOCAL_MCP_DIRECT` | off | `/api/local/mcp-direct` | 第 4 節 |
| 自動驗片 | `agent_qc.json` | `STUDIO_LOCAL_AGENT_QC` | off | `/api/local/agent-qc` | 主迴圈的 check 自己跑：接縫（SSIM）、鎖位（灰模開著才量）、驗片卡（走第 4 節）；做不了就交回呼叫端 |
| 首幀接力 | `frame_relay.json` | `STUDIO_LOCAL_FRAME_RELAY` | off | `/api/local/frame-relay` | 接續的那一鏡用上一鏡定稿的最後一格當首幀（會用你的金鑰上傳那一張） |
| 匯出引擎 | `postblocks.json` | `POSTBLOCKS_ENGINE` | legacy | `/api/local/engine` | `blocks`：匯出照後製積木的管線；`shadow`：照舊匯出、背景比對積木 |
| 介面描述檔 | `ui_profiles.json` | `STUDIO_LOCAL_UI_PROFILES` | off | `/api/local/ui-profiles` | Agent 可以組、套用你的介面 |
| 灰模首幀 | — | `STUDIO_BLOCKOUT_FRAMES` | legacy | — | `shadow`／`on`：主迴圈幫有灰模的鏡渲染首幀、量鎖位 |

另外幾個只看環境變數、預設關的：`GEN_RETRY`、`GEN_RETRY_QC`（生成失敗、品管不合格時自動重抽；主迴圈送的件一律略過，由主迴圈自己決定）、
`STUDIO_AUTO_TAKES`（人送的件自動記 take）。值都是 `off`（預設）／`shadow`（只記不做）／`on`。

## 7. 接自己的金鑰、換模型或供應商

* **金鑰**：init 的 `key`，或在 App 的設定頁貼上（伺服器向 AppleToken 驗過才收）。金鑰只在記憶體與系統鑰匙圈，不寫進 SQLite、不寫檔、不進 log。
* **模型與供應商**：生成一律經 AppleToken `/v2`，模型用 `<provider>/<name>` 的 ref 指定，
  可用的清單看 `list_models` 或 `/v2/models`。換供應商就是換 ref；各家吃哪些輸入（首幀、尾幀、參考圖、欄位名稱）
  照 `local-server/cli/appletoken/core/model_caps.py` 的實測表，表裡沒實測過的會提醒 `untested`，已知會失敗的組合直接擋下、不白花錢。
* **換 API 位址**：`--gateway-base` 可以指向相容 AppleToken `/v2` 的其他 https 端點（例如你自己架的閘道）。

## 8. 開發與測試

* `npm test`：桌面殼的測試（`test/*.test.js`）。
* `npm run prepare:local`：準備本機伺服器時，會用附的 Python 以 `python -I` 實際 import 一次 `studio_local`（印出 `ok`），
  缺檔或 import 了第三方套件會在這一步就失敗。
* 單獨跑伺服器做手動測試時，`--gateway-base` 可以指向你自己在 127.0.0.1 起的假上游，不打真的 API、不花錢。
* **`local-server/` 是從上游同步過來的**（版本記在 `local-server/SOURCE_COMMIT`）。要改它的話，請發 issue 或 PR 說明改了什麼、為什麼，
  維護者會在上游改好再同步過來；直接改 `local-server/` 的檔，下一次同步會被蓋掉。
* 新功能照第 1 節的原則：開關預設關、壞了退回、舊碼不刪。
