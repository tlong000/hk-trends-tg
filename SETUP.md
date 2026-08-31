# SETUP：香港 Google Trends 熱搜 → 本地模型解讀 → Telegram 推送

> 呢份文件係「交俾第二部電腦（有本地模型嗰部）上面嘅 AI 執行」用嘅。
> 由頭到尾跟住做，最後會有一個每 2 分鐘自動運行嘅 launchd 服務。
> （2 分鐘係你指定嘅頻率。提提你：Trending 資料唔會咁快變，頻繁 poll 對無官方
>  文件嘅內部介面有被限流風險；如 run.log 出現連續 `HTTP 429`，調大 `StartInterval`。）
> 目標行為：每次抓 `https://trends.google.com/trending?geo=HK` 背後嘅資料，
> 揀出「過去 6 小時內、搜尋量桶 ≥ 500、仍在上升」嘅熱點，
> 用本地模型寫 ≤100 字繁體中文解讀，推去指定 Telegram 群組；同一關鍵詞 48 小時內唔重複。

---

## 給執行呢份文件嘅 AI 的說明

1. **如果你係一個 context window 細（<8k token）嘅本地模型，唔好讀呢份長文**——會 context 溢出。
   改用同資料夾嘅 `SETUP-slim.md`（冇內嵌程式碼），或叫用戶自己跟住做。
2. 逐步執行「Part 1 ~ Part 6」，每一步都要把指令輸出畀用戶睇，確認 OK 先落下一步。
3. **秘密（Telegram bot token）由用戶親手貼入 `.env`**，你唔好猜、唔好代填、唔好寫入任何其他檔案或 log。
4. 用戶如果已經同你一齊搬咗程式檔（見 Part 1 清單）過嚟，就直接用；如果冇，就照「附錄」嘅完整內容自己寫出嚟。
5. 平台假設係 macOS。若係 Linux，Part 6 嘅 launchd 改用 cron 或 systemd（附錄 F 有 crontab 版本）。
6. 全部檔案放同一個資料夾，預設 `~/hk-trends-tg/`。

---

## Part 0：檢查前置

```bash
# Python 3.8+（唔使裝任何第三方套件）
python3 --version || xcode-select --install    # 冇 python3 就裝 Command Line Tools

# 本地模型服務有冇開住（兩種都試，睇邊個有回應）
curl -s --max-time 3 http://127.0.0.1:11434/api/tags   ; echo   # Ollama
curl -s --max-time 3 http://127.0.0.1:1234/v1/models    ; echo   # LM Studio / OpenAI 相容
```

- 有 `{"models":[...]}` 回應 → 用 **Ollama**，`MODEL_BASE_URL=http://127.0.0.1:11434`
- 有 `{"data":[...]}` 回應 → 用 **openai 相容**，`MODEL_BASE_URL=http://127.0.0.1:1234`
- 兩個都冇 → 問用戶佢個本地模型點跑、聽邊個 port，再對應上面兩種其中一種。
- 記低模型名：Ollama 用 `ollama list` 第一欄（例 `qwen2.5:7b`）；openai 相容用上面 `/v1/models` 回應入面嘅 `"id"`。
- **Context length**：本程式每次 prompt <1000 token，模型載入時 context ≥ 2048 就夠（建議 4096）。
  LM Studio 用戶請喺載入模型嗰版將「Context Length」設 ≥ 4096；Ollama 由 `.env` 嘅 `MODEL_NUM_CTX` 控制（預設 4096）。

---

## Part 1：放檔案

```bash
mkdir -p ~/hk-trends-tg
cd ~/hk-trends-tg
```

呢個資料夾要有以下 5 個檔（用戶搬過嚟，或你照附錄寫出嚟）：

| 檔案 | 用途 | 附錄 |
|---|---|---|
| `trends_tg_bot.py` | 主程式 | 附錄 A |
| `analysis_prompt.md` | 俾模型嘅提示 | 附錄 B |
| `run.sh` | launchd wrapper | 附錄 C |
| `com.user.hk-trends-tg.plist` | 排程設定 | 附錄 D |
| `config.example.env` | 設定樣本 | 附錄 E |

驗證：

```bash
cd ~/hk-trends-tg
ls -1
python3 -m py_compile trends_tg_bot.py && echo "trends_tg_bot.py 語法 OK"
wc -l trends_tg_bot.py      # 應該係 400 行左右
chmod +x run.sh trends_tg_bot.py
```

---

## Part 2：攞 Telegram 群組 chat id

（用戶已經有 bot token；bot 亦已經喺目標群組。）

```bash
# 1) 喺個群組隨便打一句嘢（例如 "ping"）
# 2) 跑呢句，<TOKEN> 換成用戶個 token：
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
```

喺輸出搵 `"chat": { "id": -100XXXXXXXXXX, "title": "你個群名", "type": "supergroup" }`，
嗰個 **負數** `id` 就係 `TG_CHAT_ID`。

> 搵唔到 `chat`？→ 確認 bot 真係喺群、啱啱有人喺群發過言；或者去 @BotFather → Bot Settings → Group Privacy 設做 **Disabled**，再喺群發多次。

---

## Part 3：建立 .env

```bash
cd ~/hk-trends-tg
cp config.example.env .env
chmod 600 .env
```

用你嘅編輯器改 `.env`，**淨係改呢幾行**：

```ini
MODEL_API=ollama                       # 或 openai（跟 Part 0 結果）
MODEL_BASE_URL=http://127.0.0.1:11434  # 或 http://127.0.0.1:1234
MODEL_NAME=qwen2.5:7b                   # 跟 Part 0 記低嗰個
TG_BOT_TOKEN=                           # ← 用戶親手貼，AI 唔好代填
TG_CHAT_ID=-100XXXXXXXXXX               # Part 2 攞到嗰個負數
```

其餘（`TRENDS_HOURS=6`、`MIN_TRAFFIC=500`、`MAX_PUSH_PER_RUN=5`…）預設已經啱需求，暫時唔使郁。

> `.env` 唔好 commit、唔好貼去任何地方。`chmod 600` 之後淨係你自己讀得到。

---

## Part 4：三段式測試（重要，順序做）

### 4a. 只測抓取＋過濾（唔 call 模型、唔發 Telegram）

```bash
cd ~/hk-trends-tg
MODEL_API=mock DRY_RUN=1 ./run.sh
tail -n 60 run.log
```

預期：見到 `RPC 共 N 條` → `符合門檻（6h 內 / 搜尋量>=500 / 進行中）：X 條` → 每條印出一個 `📈 香港熱搜｜…` 訊息草稿。
X 有機會係 0（嗰刻啱啱冇夠熱嘅新熱點），屬正常；想確認邏輯行到就臨時加 `TRENDS_HOURS=48` 再跑一次。

### 4b. 測真模型（仍然唔發 Telegram）

```bash
cd ~/hk-trends-tg
DRY_RUN=1 ./run.sh
tail -n 60 run.log
```

預期：每條 `📈` 訊息入面段解讀係由你本地模型寫、繁體中文、≤100 字。
- 卡住／`timeout` → 模型太慢，`.env` 加大 `MODEL_TIMEOUT=180`，或換細啲嘅模型。
- `未知 MODEL_API` / 連線 refused → `MODEL_API` 或 `MODEL_BASE_URL` 填錯，返 Part 0。
- 解讀離題／超長 → 程式會硬截到 100 字；想改語氣就改 `analysis_prompt.md`。
- **`context length ... too small` / `context ... too small for this request`**（LM Studio 字眼）
  → 你個模型載入時 context 開得太細。本程式每次 prompt 其實 <1000 token，所以：
  · **Ollama**：`.env` 已有 `MODEL_NUM_CTX=4096`，夠用；仲報錯就確認你冇喺別處 override。
  · **LM Studio**：左邊揀返個模型 → 「Load」設定版 → **Context Length 調到 8192**（最少 4096）→ Reload。
    VRAM 唔夠就同時把 GPU Offload 層數調低。
  · ⚠️ 如果你係「將成份 SETUP.md 餵咗俾本地模型去執行」先報錯 → 唔好咁做，
    改用 **SETUP-slim.md**（冇內嵌程式碼、細好多），或者自己跟住做。本地模型只負責寫 100 字解讀。

### 4c. 正式發一次

```bash
cd ~/hk-trends-tg
./run.sh
tail -n 60 run.log
```

去 Telegram 群組睇有冇收到。收到 = 成功。
（如果 4a 顯示「符合門檻 0 條」，呢步唔會發嘢，等有熱點時 launchd 會自動補；想即刻試可臨時 `MIN_TRAFFIC=200 ./run.sh`。）

---

## Part 5：清走測試殘留

```bash
cd ~/hk-trends-tg
cat state.json          # 睇下已推送記錄；想由乾淨開始就：
rm -f state.json
```

---

## Part 6：設定 launchd 每 2 分鐘自動跑

### 6a. 改 plist 入面嘅絕對路徑

`com.user.hk-trends-tg.plist` 入面有 3 個 `/Users/YOURNAME/hk-trends-tg`，要換成真實路徑。
一句搞掂（會用你當前 `$HOME`）：

```bash
cd ~/hk-trends-tg
sed -i '' "s|/Users/YOURNAME/hk-trends-tg|$HOME/hk-trends-tg|g" com.user.hk-trends-tg.plist
grep -n "$HOME/hk-trends-tg" com.user.hk-trends-tg.plist   # 應該見到 4 個位（含 log）
```

### 6b. 安裝並啟動

```bash
cp ~/hk-trends-tg/com.user.hk-trends-tg.plist ~/Library/LaunchAgents/

# 新舊 macOS 都得，二揀一：
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.hk-trends-tg.plist 2>/dev/null \
  || launchctl load ~/Library/LaunchAgents/com.user.hk-trends-tg.plist

launchctl list | grep hk-trends-tg          # 見到就係載入咗
launchctl start com.user.hk-trends-tg       # 即刻手動觸發一次
sleep 5 && tail -n 40 ~/hk-trends-tg/run.log
```

### 6c. 以後改設定要重載

```bash
launchctl bootout gui/$(id -u)/com.user.hk-trends-tg 2>/dev/null \
  || launchctl unload ~/Library/LaunchAgents/com.user.hk-trends-tg.plist
# 改完 .env 或 plist 之後再 bootstrap/load 一次（同 6b）
```

完成。之後系統會每 2 分鐘自己跑一次，log 喺 `~/hk-trends-tg/run.log`。
（launchd 特性：上一次未跑完，下一次會自動跳過，唔會疊起兩個 instance。
 想改頻率就改 plist 個 `<integer>` 秒數，再重做 6c 重載。）

---

## 除錯對照表

| 現象（run.log） | 原因 | 處理 |
|---|---|---|
| `FATAL: 搵唔到 prompt 檔` | `analysis_prompt.md` 唔喺同一資料夾 | 補返檔案（附錄 B） |
| `WARN: 抓 Trending Now 暫時失敗，今次略過` | 冇網 / 被限流（429）/ 一時 5xx | 偶爾出現無妨（下次排程自動補）；連續出現就調大 `StartInterval` |
| `FATAL: 抓 Trending Now 解析失敗（介面可能改咗）` | Google 內部介面格式變咗 | 先試 `curl`；見下「Plan B」 |
| run.log 密集出現 `RPC HTTP 429` | poll 太頻密被 Google 限流 | 把 plist `StartInterval` 由 120 調到 300 或以上，重載 |
| `符合門檻 … 0 條`（長期） | 門檻太高 / 冇熱點 | 暫時 `MIN_TRAFFIC=300` 或 `TRENDS_HOURS=12` |
| `[XXX] 失敗，跳過：Connection refused` | 本地模型冇開 / URL 錯 | 開返模型服務，核對 `MODEL_BASE_URL` |
| `context length too small` / `context too small for this request` | 模型載入 context 太細（或有人將成份長文餵咗俾佢） | Ollama：`.env` `MODEL_NUM_CTX=4096`；LM Studio：載入版 Context Length 調 8192 後 Reload；唔好將 SETUP.md 全文餵本地模型（用 SETUP-slim.md） |
| `[XXX] 失敗，跳過：Telegram 回傳錯誤` | token/chat_id 錯 / bot 唔喺群 | 重做 Part 2、Part 3 |
| Telegram 冇反應但 log 話已推送 | `TG_CHAT_ID` 唔啱（要負數 supergroup id） | 重攞 chat id |
| launchd 冇跑 | plist 路徑未換 / 未 bootstrap | 重做 Part 6a、6b |

### Plan B：萬一 Google 內部介面壞咗

`trends_tg_bot.py` 仍保留舊 RSS 端點喺 `fetch_rss_news_map()`。應急做法：把 `fetch_trends()` 改為讀
`https://trends.google.com/trending/rss?geo=HK`，每個 `<item>` 取 `<title>`、`<ht:approx_traffic>`（"500+" → 500）、
`<pubDate>`（換算 6 小時窗），其餘流程不變。呢個 RSS 較穩定但係「每日」粒度、桶係字串。

---

## 附錄 A：`trends_tg_bot.py`

> 如果檔案已經一齊搬過嚟，直接用嗰個、跳過呢段。
> 如果手上淨係得呢份 MD，就將下面成段一字不差寫入 `~/hk-trends-tg/trends_tg_bot.py`。

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
香港 Google Trends「Trending Now」熱點 → 本地模型解讀 → Telegram 群組推送

資料來源＝ https://trends.google.com/trending?geo=HK 呢個頁面背後嘅內部介面
（batchexecute RPC，RPC id = i0OFE）。相比舊 RSS：
  - 支援 server 端「過去 N 小時」過濾（直接對應「6 小時內」需求）
  - 每條有「數值」搜尋量（100 / 200 / 500 / 2000 / 20000…），唔使夾硬 parse "500+"
  - 有「trend 係咪已完結」flag，可淨要進行中嘅
  - 有相關搜尋詞，夠俾模型判斷背景

新聞標題：另外抓官方 Trending RSS，按關鍵詞比對補上（best-effort，失敗照跑）。

設計原則：零第三方套件（只用標準庫）；任何一步失敗只跳過該條，唔會 crash。
Python 3.8+ 相容。所有設定行 environment variable 傳入（見 config.example.env）。
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# 載入 .env（跨平台；毋須第三方套件。已存在嘅環境變數優先）
# ---------------------------------------------------------------------------

def _load_dotenv(path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, val)
    except OSError:
        pass


_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, ".env"), os.path.join(os.getcwd(), ".env")):
    _load_dotenv(_p)


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

TRENDS_GEO = os.environ.get("TRENDS_GEO", "HK")
TRENDS_HOURS = int(os.environ.get("TRENDS_HOURS", "6"))          # server 端時間窗
MIN_TRAFFIC = int(os.environ.get("MIN_TRAFFIC", "500"))          # 搜尋量門檻
INCLUDE_ENDED = os.environ.get("INCLUDE_ENDED", "0") == "1"      # 係咪連「已完結」都推
MAX_PUSH_PER_RUN = int(os.environ.get("MAX_PUSH_PER_RUN", "5"))
DEDUP_TTL_HOURS = float(os.environ.get("DEDUP_TTL_HOURS", "48"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "100"))
TG_LINK_PREVIEW = os.environ.get("TG_LINK_PREVIEW", "0") == "1"   # =1 顯示新聞連結預覽卡
MAX_RELATED = int(os.environ.get("MAX_RELATED", "4"))             # 相關詞 / hashtag 上限

TRENDS_RPC_URL = os.environ.get(
    "TRENDS_RPC_URL", "https://trends.google.com/_/TrendsUi/data/batchexecute"
)
TRENDS_RSS_URL = os.environ.get(
    "TRENDS_RSS_URL", "https://trends.google.com/trending/rss?geo=HK"
)

def _rel(p: str) -> str:
    """相對路徑一律當作「腳本所在資料夾」下面，令排程器點樣叫都搵到檔。"""
    return p if os.path.isabs(p) else os.path.join(_HERE, p)


STATE_FILE = _rel(os.environ.get("STATE_FILE", "state.json"))
PROMPT_FILE = _rel(os.environ.get("PROMPT_FILE", "analysis_prompt.md"))
LOG_PREFIX = "[hk-trends-tg]"

# 本地模型
MODEL_API = os.environ.get("MODEL_API", "ollama").strip().lower()  # ollama | openai | mock
MODEL_BASE_URL = os.environ.get("MODEL_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen2.5:7b")
MODEL_API_KEY = os.environ.get("MODEL_API_KEY", "")
MODEL_TIMEOUT = float(os.environ.get("MODEL_TIMEOUT", "90"))
MODEL_NUM_CTX = int(os.environ.get("MODEL_NUM_CTX", "4096"))  # Ollama 載入 context 長度

# Telegram
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
TG_TIMEOUT = float(os.environ.get("TG_TIMEOUT", "30"))

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

HTTP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HT_NS = "https://trends.google.com/trending/rss"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def log(*args: object) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(LOG_PREFIX, ts, *args, flush=True)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def http_get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": HTTP_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_post(url: str, body: bytes, timeout: float, headers: dict) -> str:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def http_post_json(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    hdr = {"Content-Type": "application/json", "User-Agent": HTTP_UA}
    if headers:
        hdr.update(headers)
    raw = http_post(url, json.dumps(payload).encode("utf-8"), timeout, hdr)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 1. 抓 Trending Now（batchexecute RPC）
# ---------------------------------------------------------------------------

def fetch_trends() -> list[dict]:
    """回傳 [{keyword, volume:int, started:datetime, ended:bool, related:[str]}]。"""
    inner = json.dumps([None, None, TRENDS_GEO, 0, "en", TRENDS_HOURS, 1])
    freq = json.dumps([[["i0OFE", inner, None, "generic"]]])
    body = urllib.parse.urlencode({"f.req": freq}).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": HTTP_UA,
    }
    log(f"抓 Trending Now RPC: geo={TRENDS_GEO} hours={TRENDS_HOURS}")
    raw = None
    for attempt in (1, 2, 3):
        try:
            raw = http_post(TRENDS_RPC_URL, body, timeout=30, headers=headers)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                wait = 5 * attempt
                log(f"RPC HTTP {e.code}，{wait}s 後重試（{attempt}/2）")
                time.sleep(wait)
                continue
            raise
    if raw is None:
        raise urllib.error.URLError("RPC 重試耗盡")

    text = raw.lstrip()
    if text.startswith(")]}'"):
        text = text[4:].lstrip()
    envelope = json.loads(text)

    payload = None
    for row in envelope:
        if isinstance(row, list) and len(row) >= 3 and row[0] == "wrb.fr" and row[1] == "i0OFE":
            payload = row[2]
            break
    if not payload:
        raise ValueError("RPC 回應搵唔到 i0OFE payload")

    rows = json.loads(payload)[1] or []
    out: list[dict] = []
    for r in rows:
        try:
            keyword = (r[0] or "").strip()
            volume = int(r[6]) if r[6] is not None else 0
            started = (
                datetime.fromtimestamp(r[3][0], tz=timezone.utc)
                if r[3] and r[3][0] else None
            )
            ended = bool(r[4] and r[4][0])
            related = [q for q in (r[9] or []) if q and q != keyword]
        except (IndexError, TypeError, ValueError):
            continue
        if keyword:
            out.append(
                {
                    "keyword": keyword,
                    "volume": volume,
                    "started": started,
                    "ended": ended,
                    "related": related,
                    "news": [],
                }
            )
    log(f"RPC 共 {len(out)} 條")
    return out


def qualifies(it: dict) -> bool:
    if not it["keyword"]:
        return False
    if it["volume"] < MIN_TRAFFIC:
        return False
    if it["ended"] and not INCLUDE_ENDED:
        return False
    if it["started"] is not None:
        age = now_utc() - it["started"]
        if age < timedelta(0) or age > timedelta(hours=TRENDS_HOURS):
            return False
    return True


# ---------------------------------------------------------------------------
# 2. 抓 RSS 補新聞標題（best-effort）
# ---------------------------------------------------------------------------

def fetch_rss_news_map() -> dict:
    """{keyword: [{title,url,source}]}；失敗回傳 {}。"""
    try:
        raw = http_get(TRENDS_RSS_URL, timeout=20)
        root = ET.fromstring(raw)
    except (urllib.error.URLError, ET.ParseError, TimeoutError) as e:
        log("RSS 補新聞失敗（略過）:", e)
        return {}
    m: dict = {}
    for item in root.findall("./channel/item"):
        kw = (item.findtext("title") or "").strip()
        if not kw:
            continue
        news = []
        for n in item.findall(f"{{{HT_NS}}}news_item"):
            t = html.unescape((n.findtext(f"{{{HT_NS}}}news_item_title") or "").strip())
            u = (n.findtext(f"{{{HT_NS}}}news_item_url") or "").strip()
            s = (n.findtext(f"{{{HT_NS}}}news_item_source") or "").strip()
            if t and u:
                news.append({"title": t, "url": u, "source": s})
        if news:
            m[kw] = news
    return m


def attach_news(items: list[dict], news_map: dict) -> None:
    for it in items:
        if it["keyword"] in news_map:
            it["news"] = news_map[it["keyword"]]


# ---------------------------------------------------------------------------
# 3. 去重 state
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"pushed": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("pushed", {})
        return data
    except (json.JSONDecodeError, OSError):
        log("state.json 讀唔到，重建")
        return {"pushed": {}}


def prune_state(state: dict) -> None:
    cutoff = now_utc() - timedelta(hours=DEDUP_TTL_HOURS)
    kept = {}
    for kw, iso in state.get("pushed", {}).items():
        try:
            if datetime.fromisoformat(iso) >= cutoff:
                kept[kw] = iso
        except ValueError:
            continue
    state["pushed"] = kept


def save_state(state: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------------------
# 4. 本地模型解讀
# ---------------------------------------------------------------------------

def load_prompt_template() -> tuple[str, str]:
    if not os.path.exists(PROMPT_FILE):
        raise FileNotFoundError(f"搵唔到 prompt 檔：{PROMPT_FILE}")
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    sys_part, _, rest = text.partition("=== USER ===")
    sys_part = sys_part.split("=== SYSTEM ===", 1)[-1].strip()
    user_part = rest.strip()
    if not sys_part or not user_part:
        raise ValueError("prompt 檔缺少 === SYSTEM === 或 === USER === 區段")
    return sys_part, user_part


def build_messages(it: dict, sys_tmpl: str, user_tmpl: str) -> list[dict]:
    if it["news"]:
        ctx = "\n".join(f"- {n['source'] or '來源不明'}：{n['title']}" for n in it["news"][:5])
    elif it["related"]:
        ctx = "相關搜尋詞：" + "、".join(it["related"][:8])
    else:
        ctx = "-（暫無相關新聞或相關詞）"
    user = (
        user_tmpl.replace("{keyword}", it["keyword"])
        .replace("{traffic}", f"{it['volume']}+")
        .replace("{news}", ctx)
    )
    return [
        {"role": "system", "content": sys_tmpl},
        {"role": "user", "content": user},
    ]


def call_model(messages: list[dict]) -> str:
    if MODEL_API == "mock":
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        kw = ""
        for line in user.splitlines():
            if line.startswith("關鍵詞："):
                kw = line.split("：", 1)[1].strip()
        return f"（測試輸出）「{kw}」近期搜尋量明顯上升，暫以此為佔位文字，正式運行時會由本地模型生成不超過 100 字嘅事實解讀。"

    if MODEL_API == "ollama":
        url = f"{MODEL_BASE_URL}/api/chat"
        payload = {"model": MODEL_NAME, "messages": messages, "stream": False,
                   "options": {"temperature": 0.3, "num_ctx": MODEL_NUM_CTX}}
        resp = http_post_json(url, payload, MODEL_TIMEOUT)
        return (resp.get("message", {}) or {}).get("content", "").strip()

    if MODEL_API == "openai":
        url = f"{MODEL_BASE_URL}/v1/chat/completions"
        payload = {"model": MODEL_NAME, "messages": messages, "stream": False,
                   "temperature": 0.3}
        headers = {"Authorization": f"Bearer {MODEL_API_KEY}"} if MODEL_API_KEY else None
        resp = http_post_json(url, payload, MODEL_TIMEOUT, headers=headers)
        return resp["choices"][0]["message"]["content"].strip()

    raise ValueError(f"未知 MODEL_API：{MODEL_API}（ollama / openai / mock）")


def tidy_interpretation(text: str) -> str:
    t = " ".join(text.split())
    for lead in ("解讀：", "解讀:", "摘要：", "摘要:"):
        if t.startswith(lead):
            t = t[len(lead):].strip()
    if len(t) > MAX_CHARS:
        t = t[: MAX_CHARS - 1].rstrip() + "…"
    return t


# ---------------------------------------------------------------------------
# 5. Telegram
# ---------------------------------------------------------------------------

def tg_send(text: str) -> None:
    if DRY_RUN:
        log("DRY_RUN，唔會真係發：\n" + text)
        return
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        raise ValueError("TG_BOT_TOKEN / TG_CHAT_ID 未設定")
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": not TG_LINK_PREVIEW,
    }
    resp = http_post_json(url, payload, TG_TIMEOUT)
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram 回傳錯誤：{resp}")


def _esc(s: str) -> str:
    """HTML parse_mode 下要 escape 嘅字元。"""
    return html.escape(s or "", quote=False)


def _hashtags(it: dict) -> str:
    seen: set = set()
    tags: list = []

    def add(raw: str) -> None:
        t = "".join(ch for ch in (raw or "") if ch.isalnum())
        if t and 1 < len(t) <= 20 and t.lower() not in seen:
            seen.add(t.lower())
            tags.append("#" + t)

    add("香港熱搜")
    add(it["keyword"])
    for q in it["related"][:MAX_RELATED]:
        if len(tags) >= 4:
            break
        add(q)
    return " ".join(tags[:4])


def format_message(it: dict, interpretation: str) -> str:
    lines = [
        f"📈 <b>{_esc(it['keyword'])}</b> · 🔍 {it['volume']}+",
        "",
        _esc(interpretation),
        "",
    ]
    top = it["news"][0] if it["news"] else None
    if top and top.get("url"):
        label = _esc(top["title"])
        if top.get("source"):
            label += f"（{_esc(top['source'])}）"
        lines.append(f'📰 <a href="{html.escape(top["url"], quote=True)}">{label}</a>')
    else:
        q = urllib.parse.quote(it["keyword"])
        gurl = f"https://news.google.com/search?q={q}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
        lines.append(f'📰 <a href="{gurl}">Google 新聞：{_esc(it["keyword"])}</a>')

    if it["related"]:
        lines.append("🔎 " + _esc("、".join(it["related"][:MAX_RELATED])))

    tags = _hashtags(it)
    if tags:
        lines.append(tags)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        sys_tmpl, user_tmpl = load_prompt_template()
    except (FileNotFoundError, ValueError) as e:
        log("FATAL:", e)
        return 2

    try:
        items = fetch_trends()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        # 網絡／限流等暫時性問題：今次略過，等下一次排程，唔當硬錯誤
        log("WARN: 抓 Trending Now 暫時失敗，今次略過:", e)
        return 0
    except (ValueError, json.JSONDecodeError) as e:
        # 解析唔到 = 內部介面格式可能變咗，要人跟進
        log("FATAL: 抓 Trending Now 解析失敗（介面可能改咗）:", e)
        return 1

    attach_news(items, fetch_rss_news_map())

    state = load_state()
    prune_state(state)

    candidates = [it for it in items if qualifies(it)]
    log(f"符合門檻（{TRENDS_HOURS}h 內 / 搜尋量>={MIN_TRAFFIC} / 進行中）：{len(candidates)} 條")

    fresh = [it for it in candidates if it["keyword"] not in state["pushed"]]
    log(f"未推送過：{len(fresh)} 條")

    pushed = 0
    for it in fresh:
        if pushed >= MAX_PUSH_PER_RUN:
            log("已達單次上限", MAX_PUSH_PER_RUN)
            break
        kw = it["keyword"]
        try:
            raw = call_model(build_messages(it, sys_tmpl, user_tmpl))
            if not raw:
                log(f"[{kw}] 模型回傳空，跳過")
                continue
            interp = tidy_interpretation(raw)
            tg_send(format_message(it, interp))
            state["pushed"][kw] = now_utc().isoformat()
            save_state(state)
            pushed += 1
            log(f"[{kw}] 已推送（{len(interp)} 字，搜尋量 {it['volume']}+）")
            time.sleep(1)
        except (urllib.error.URLError, KeyError, ValueError, RuntimeError, TimeoutError) as e:
            log(f"[{kw}] 失敗，跳過：{e}")
            continue

    log(f"完成，今次推送 {pushed} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## 附錄 B：`analysis_prompt.md`

```markdown
=== SYSTEM ===
你係香港新聞編輯，專為 Telegram 頻道寫「熱搜速報」。
你會收到一個 Google Trends 香港熱門關鍵詞、佢近期嘅搜尋量，同幾條相關新聞標題。
你要用繁體中文寫一段「解讀」，向香港讀者解釋：呢個關鍵詞點解會突然熱門、背後發生咩事、對佢哋有咩實際意思。

硬性要求：
- 不超過 100 個中文字。
- 一段過，唔好分點、唔好標題、唔好 emoji、唔好加「解讀：」呢類前綴。
- 只寫已知事實同合理背景；唔好作新聞、唔好投資／政治立場、唔好誇張形容詞。
- 如果相關新聞不足以判斷原因，就照直講「暫時未有明確原因，僅見搜尋量上升」，再補一兩句已知資訊。

=== USER ===
關鍵詞：{keyword}
近期搜尋量：{traffic}
相關新聞標題：
{news}

請直接輸出解讀內文（繁體中文，不超過 100 字）：
```

## 附錄 C：`run.sh`

```bash
#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
PY="$(command -v python3 || true)"
[ -z "$PY" ] && PY="/usr/bin/python3"
exec "$PY" "$HERE/trends_tg_bot.py" >> "$HERE/run.log" 2>&1
```

## 附錄 D：`com.user.hk-trends-tg.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.hk-trends-tg</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/YOURNAME/hk-trends-tg/run.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOURNAME/hk-trends-tg</string>
    <key>StartInterval</key>
    <integer>120</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/YOURNAME/hk-trends-tg/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOURNAME/hk-trends-tg/launchd.err.log</string>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
```

## 附錄 E：`config.example.env`

```ini
TRENDS_GEO=HK
TRENDS_HOURS=6
MIN_TRAFFIC=500
INCLUDE_ENDED=0
MAX_PUSH_PER_RUN=5
DEDUP_TTL_HOURS=48
MAX_CHARS=100
STATE_FILE=state.json
PROMPT_FILE=analysis_prompt.md

MODEL_API=ollama
MODEL_BASE_URL=http://127.0.0.1:11434
MODEL_NAME=qwen2.5:7b
MODEL_API_KEY=
MODEL_TIMEOUT=90

TG_BOT_TOKEN=
TG_CHAT_ID=

DRY_RUN=0
```

## 附錄 F：Linux 版排程（用 crontab 代替 launchd）

```bash
chmod +x ~/hk-trends-tg/run.sh
( crontab -l 2>/dev/null; echo "*/30 * * * * cd $HOME/hk-trends-tg && ./run.sh" ) | crontab -
crontab -l
```
