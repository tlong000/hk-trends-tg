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

狀態 / 控制（無需長開 process，跟住 cron 走）：
  - 每次 run 讀一次 getUpdates，處理 /status /pause /resume /runnow ＋ inline 按鈕
  - 每次 run edit 一條 pinned「心跳」訊息（最後檢查時間 / 今日推咗幾多 / 下次約幾點）
  - 「已暫停」時只更新心跳，唔抓唔推
  - 抓取解析失敗（介面改咗）會發 ⚠️ DM 去 TG_ADMIN_CHAT_ID
部署：本機 launchd/Task Scheduler，或 GitHub Actions cron（見 SETUP-cloud.md）。

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
# 心跳訊息 + 開關掣放邊個 chat；預設同推送目標同一個群。
# 建議設做「你同 bot 嘅私訊」或細管理群，避免洗版。
TG_ADMIN_CHAT_ID = os.environ.get("TG_ADMIN_CHAT_ID", "").strip() or TG_CHAT_ID
TG_TIMEOUT = float(os.environ.get("TG_TIMEOUT", "30"))

# 心跳（每次 run edit 一條 pinned message 顯示運行狀態）
TG_HEARTBEAT = os.environ.get("TG_HEARTBEAT", "1") == "1"
# 指令（每次 run 讀一次 getUpdates：/status /pause /resume /runnow + inline 按鈕）
TG_CONTROLS = os.environ.get("TG_CONTROLS", "1") == "1"
# 排程間隔（分鐘），只用嚟喺心跳顯示「下次約 HH:MM」
NEXT_RUN_MINUTES = int(os.environ.get("NEXT_RUN_MINUTES", "15"))

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

HKT = timezone(timedelta(hours=8))

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


def hkt_now() -> datetime:
    return datetime.now(HKT)


def fmt_ago(iso: str) -> str:
    """把 ISO 時間變做「3 分鐘前」呢類人話。"""
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return "未知"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = (now_utc() - then).total_seconds()
    if secs < 0:
        return "啱啱"
    if secs < 90:
        return f"{int(secs)} 秒前"
    if secs < 5400:
        return f"{int(secs // 60)} 分鐘前"
    if secs < 172800:
        return f"{int(secs // 3600)} 小時前"
    return f"{int(secs // 86400)} 日前"


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

def tg_api(method: str, payload: dict, timeout: float | None = None) -> dict:
    """打一個 Telegram Bot API method，回傳 response dict（唔會 raise，畀 caller 自己睇 ok）。"""
    if not TG_BOT_TOKEN:
        return {"ok": False, "description": "TG_BOT_TOKEN 未設定"}
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}"
    try:
        return http_post_json(url, payload, timeout or TG_TIMEOUT)
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def tg_send(text: str) -> None:
    if DRY_RUN:
        log("DRY_RUN，唔會真係發：\n" + text)
        return
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        raise ValueError("TG_BOT_TOKEN / TG_CHAT_ID 未設定")
    resp = tg_api("sendMessage", {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": not TG_LINK_PREVIEW,
    })
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram 回傳錯誤：{resp}")


def notify_admin(text: str) -> None:
    """出事時通知管理員（best-effort，唔會 raise）。"""
    if DRY_RUN:
        log("DRY_RUN，唔會通知 admin：" + text)
        return
    if not TG_BOT_TOKEN or not TG_ADMIN_CHAT_ID:
        return
    tg_api("sendMessage", {
        "chat_id": TG_ADMIN_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    })


# ---------------------------------------------------------------------------
# 5b. 心跳訊息 + 開關掣（全部走 cron，唔使長開 process）
# ---------------------------------------------------------------------------

_RESULT_LABEL = {
    "ok": "正常",
    "warn": "來源暫時失敗（下次自動重試）",
    "fatal": "介面異常，需要跟進",
    "paused": "已暫停",
}


def status_text(state: dict, result: str = "ok") -> str:
    paused = bool(state.get("paused"))
    head = "⏸ 已暫停" if paused else "▶️ 運行中"
    last = state.get("last_run")
    last_line = f"{fmt_ago(last)}" if last else "未有記錄"
    nxt = (hkt_now() + timedelta(minutes=NEXT_RUN_MINUTES)).strftime("%H:%M")
    lines = [
        "📊 <b>香港熱搜推送 · 狀態</b>",
        f"狀態：{head}",
        f"最後檢查：{last_line}",
        f"最後結果：{_RESULT_LABEL.get(result, result)}",
        f"今日已推：{int(state.get('pushed_today', 0))} 條",
        f"排程：每 {NEXT_RUN_MINUTES} 分鐘（GitHub Actions）",
    ]
    if not paused:
        lines.append(f"下次約 {nxt}")
    return "\n".join(lines)


def _heartbeat_markup(paused: bool) -> dict:
    btn = ({"text": "▶️ 開", "callback_data": "hb:resume"} if paused
           else {"text": "⏸ 暫停", "callback_data": "hb:pause"})
    return {"inline_keyboard": [[btn], [{"text": "🔄 即刻檢查", "callback_data": "hb:runnow"}]]}


def write_heartbeat(state: dict, result: str = "ok") -> None:
    """Edit（冇就新開 + pin）一條 pinned message 顯示運行狀態。任何錯只 log。"""
    if not TG_HEARTBEAT:
        return
    if DRY_RUN:
        log("DRY_RUN，心跳訊息內容：\n" + status_text(state, result))
        return
    if not TG_BOT_TOKEN or not TG_ADMIN_CHAT_ID:
        return
    text = status_text(state, result)
    markup = _heartbeat_markup(bool(state.get("paused")))
    mid = state.get("heartbeat_message_id")
    same_chat = str(state.get("heartbeat_chat_id", "")) == str(TG_ADMIN_CHAT_ID)
    if mid and same_chat:
        r = tg_api("editMessageText", {
            "chat_id": TG_ADMIN_CHAT_ID, "message_id": mid,
            "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True, "reply_markup": markup,
        })
        # 「message is not modified」當成功；其餘錯就重開
        if r.get("ok") or "not modified" in str(r.get("description", "")).lower():
            return
        log("心跳 edit 失敗，重開一條：", r.get("description"))
    r = tg_api("sendMessage", {
        "chat_id": TG_ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True, "reply_markup": markup,
    })
    if r.get("ok"):
        state["heartbeat_message_id"] = r["result"]["message_id"]
        state["heartbeat_chat_id"] = TG_ADMIN_CHAT_ID
        save_state(state)  # 即刻落盤，否則下次 run 又會新開一條（洗版）
        tg_api("pinChatMessage", {
            "chat_id": TG_ADMIN_CHAT_ID,
            "message_id": r["result"]["message_id"],
            "disable_notification": True,
        })
    else:
        log("心跳 sendMessage 失敗：", r.get("description"))


def _reply(chat_id, text: str) -> None:
    tg_api("sendMessage", {"chat_id": chat_id, "text": text,
                           "disable_web_page_preview": True})


def drain_commands(state: dict) -> None:
    """讀一次 getUpdates，處理 /status /pause /resume /runnow + inline 按鈕。

    只認 TG_ADMIN_CHAT_ID / TG_CHAT_ID 發嘅指令。offset 存喺 state，下次唔會重覆處理。
    注意：若個 bot 設過 webhook，getUpdates 會失敗——呢個部署方式要用 polling。
    """
    if not TG_CONTROLS or not TG_BOT_TOKEN or DRY_RUN:
        return
    allowed = {str(TG_ADMIN_CHAT_ID), str(TG_CHAT_ID)}
    allowed.discard("")
    offset = int(state.get("tg_offset", 0))
    r = tg_api("getUpdates", {
        "offset": offset, "timeout": 0, "limit": 50,
        "allowed_updates": ["message", "callback_query"],
    }, timeout=20)
    if not r.get("ok"):
        log("getUpdates 失敗（略過指令）：", r.get("description"))
        return
    updates = r.get("result", [])
    max_uid = offset - 1
    for u in updates:
        max_uid = max(max_uid, int(u.get("update_id", max_uid)))
        msg = u.get("message") or {}
        cq = u.get("callback_query") or {}
        if msg:
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            if chat_id not in allowed:
                continue
            cmd = (msg.get("text") or "").strip().split()[0].split("@")[0].lower()
            if cmd == "/pause":
                state["paused"] = True
                _reply(chat_id, "⏸ 已暫停。之後嘅檢查唔會推送，直到 /resume 或㩒「▶️ 開」。")
            elif cmd == "/resume":
                state["paused"] = False
                _reply(chat_id, "▶️ 已恢復，下次排程會照常檢查同推送。")
            elif cmd == "/status":
                _reply(chat_id, _plain(status_text(state)))
            elif cmd == "/runnow":
                _reply(chat_id, "✅ 收到，今次已經即刻檢查緊；如果啱啱先跑完，等下一個排程。")
        elif cq:
            frm = str((cq.get("message") or {}).get("chat", {}).get("id", ""))
            data = (cq.get("data") or "")
            if frm not in allowed:
                tg_api("answerCallbackQuery", {"callback_query_id": cq.get("id")})
                continue
            if data == "hb:pause":
                state["paused"] = True
                ack = "已暫停"
            elif data == "hb:resume":
                state["paused"] = False
                ack = "已恢復"
            elif data == "hb:runnow":
                ack = "今次已經即刻檢查緊"
            else:
                ack = ""
            tg_api("answerCallbackQuery", {"callback_query_id": cq.get("id"),
                                           "text": ack})
    if updates:
        state["tg_offset"] = max_uid + 1


def _plain(html_text: str) -> str:
    """心跳文字有少量 <b>，畀純文字 reply 用。"""
    return html_text.replace("<b>", "").replace("</b>", "")


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

def _roll_daily(state: dict) -> None:
    today = hkt_now().strftime("%Y-%m-%d")
    if state.get("pushed_date") != today:
        state["pushed_date"] = today
        state["pushed_today"] = 0


def main() -> int:
    state = load_state()
    prune_state(state)

    # 先處理客戶指令（/pause /resume /status /runnow + 按鈕），offset 即刻落盤
    drain_commands(state)
    _roll_daily(state)
    save_state(state)

    # 暫停中：唔抓唔推，只更新心跳
    if state.get("paused"):
        log("狀態＝已暫停，略過今次檢查")
        state["last_run"] = now_utc().isoformat()
        state["last_result"] = "paused"
        save_state(state)
        write_heartbeat(state, "paused")
        return 0

    try:
        sys_tmpl, user_tmpl = load_prompt_template()
    except (FileNotFoundError, ValueError) as e:
        log("FATAL:", e)
        state["last_run"] = now_utc().isoformat()
        state["last_result"] = "fatal"
        save_state(state)
        notify_admin(f"⚠️ 香港熱搜推送：{e}（exit 2）")
        write_heartbeat(state, "fatal")
        return 2

    try:
        items = fetch_trends()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        # 網絡／限流等暫時性問題：今次略過，等下一次排程，唔當硬錯誤
        log("WARN: 抓 Trending Now 暫時失敗，今次略過:", e)
        state["last_run"] = now_utc().isoformat()
        state["last_result"] = "warn"
        save_state(state)
        write_heartbeat(state, "warn")
        return 0
    except (ValueError, json.JSONDecodeError) as e:
        # 解析唔到 = 內部介面格式可能變咗，要人跟進
        log("FATAL: 抓 Trending Now 解析失敗（介面可能改咗）:", e)
        state["last_run"] = now_utc().isoformat()
        state["last_result"] = "fatal"
        save_state(state)
        notify_admin(f"⚠️ 香港熱搜推送：抓 Trending Now 解析失敗，Google 內部介面可能改咗。{e}（exit 1）")
        write_heartbeat(state, "fatal")
        return 1

    candidates = [it for it in items if qualifies(it)]
    log(f"符合門檻（{TRENDS_HOURS}h 內 / 搜尋量>={MIN_TRAFFIC} / 進行中）：{len(candidates)} 條")

    fresh = [it for it in candidates if it["keyword"] not in state["pushed"]]
    log(f"未推送過：{len(fresh)} 條")

    # 有嘢要推先去抓 RSS 補新聞標題（省一個 HTTP call）
    if fresh:
        attach_news(fresh, fetch_rss_news_map())

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
            state["pushed_today"] = int(state.get("pushed_today", 0)) + 1
            save_state(state)
            pushed += 1
            log(f"[{kw}] 已推送（{len(interp)} 字，搜尋量 {it['volume']}+）")
            time.sleep(1)
        except (urllib.error.URLError, KeyError, ValueError, RuntimeError, TimeoutError) as e:
            log(f"[{kw}] 失敗，跳過：{e}")
            continue

    state["last_run"] = now_utc().isoformat()
    state["last_result"] = "ok"
    save_state(state)
    write_heartbeat(state, "ok")
    log(f"完成，今次推送 {pushed} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
