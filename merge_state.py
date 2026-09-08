#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本機 state 檔同 git 上面某個 ref 嗰份合併，結果寫返本機。

點解要有呢個檔：排程 loop 同手動 run 會同時寫同一個 state 檔，其中一邊 git push
必然被 reject。用 rebase 解衝突嘅話，其中一邊嘅「已推過」記錄會消失，下一 run
就會把嗰啲熱點再推一次（群組收到重複訊息）。

所以呢度唔做「邊份贏」，做 union：
  - pushed：兩邊嘅 key 全部保留，撞名取時間較新嗰個
  - 計數器：取大
「已推過」漏咗嘅代價係洗版，多咗嘅代價只係少推一條 —— 一律偏向保留。

用法：merge_state.py <git-ref> <state 檔> [state 檔 ...]
攞唔到 ref 上面嗰份（例如第一次加呢個檔）就當佢係空，唔算錯。
"""
import json
import subprocess
import sys


def load_ref(ref: str, path: str) -> dict:
    try:
        raw = subprocess.run(["git", "show", f"{ref}:{path}"],
                             capture_output=True, check=True).stdout
        return json.loads(raw.decode("utf-8"))
    except (subprocess.CalledProcessError, ValueError):
        return {}


def load_local(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def merge(mine: dict, theirs: dict) -> dict:
    out = dict(theirs)
    out.update({k: v for k, v in mine.items() if k != "pushed"})
    pushed = dict(theirs.get("pushed", {}))
    for kw, iso in mine.get("pushed", {}).items():
        # 撞名取時間較新嗰個，令 48 小時 TTL 由最後一次推送計起
        if kw not in pushed or str(iso) > str(pushed[kw]):
            pushed[kw] = iso
    out["pushed"] = pushed
    for key in ("pushed_today", "tg_offset", "heartbeat_message_id"):
        a, b = mine.get(key), theirs.get(key)
        if isinstance(a, int) and isinstance(b, int):
            out[key] = max(a, b)
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：merge_state.py <git-ref> <state 檔> [...]", file=sys.stderr)
        return 2
    ref, paths = sys.argv[1], sys.argv[2:]
    for path in paths:
        mine, theirs = load_local(path), load_ref(ref, path)
        if not mine and not theirs:
            continue
        merged = merge(mine, theirs)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"{path}: 本機 {len(mine.get('pushed', {}))} 條 + "
              f"{ref} {len(theirs.get('pushed', {}))} 條 → {len(merged['pushed'])} 條")
    return 0


if __name__ == "__main__":
    sys.exit(main())
