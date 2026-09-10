#!/usr/bin/env python3
"""朝の拾いもの — ページ組み立て。

毎朝のタスクはこれを clone して実行する。ページ本体（数十KB）を
会話に流さずディスク上で処理するのが目的。

使い方:
    # 既存ページ(HTML)に今日の分を足して新しいページを作る
    python build.py --page current.html --new today.json --date 2026-09-12 --out new.html

    # 初回（既存ページなし）
    python build.py --new today.json --date 2026-09-12 --out new.html

today.json の形式:
    [{"title": "...", "url": "...", "source": "...", "topic": "...",
      "thumb": ""}, ...]
    thumb は省略可。pinned に足したいものは "pin": true を付ける。
"""

import argparse, base64, hashlib, json, os, re, sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

KEEP_DAYS = 30
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILE = os.path.join(HERE, "page_body.html")
DROP_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|ref$|from$|src$)")

# ---------- URL の正規化と指紋 ----------

def normalize(url):
    s = urlsplit(url.strip())
    host = s.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    q = urlencode([(k, v) for k, v in parse_qsl(s.query) if not DROP_PARAMS.match(k)])
    path = s.path.rstrip("/") or "/"
    return urlunsplit((s.scheme.lower(), host, path, q, ""))

def fp(url):
    return hashlib.sha1(normalize(url).encode()).hexdigest()[:12]

# ---------- 既存ページから状態を取り出す ----------

STATE_RE = re.compile(r"const STATE = (\{.*?\});\s*\n", re.S)

def state_from_page(path):
    html = open(path, encoding="utf-8").read()
    m = STATE_RE.search(html)
    if not m:
        raise SystemExit("既存ページから STATE を取り出せませんでした")
    return json.loads(m.group(1))

def blank_state():
    return {"updated": "", "days": [], "pinned": [], "seen": [],
            "feedback": {"liked": [], "hidden": [], "hiddenSources": []}}

# ---------- 1日分を追加 ----------

def add_day(st, date, items):
    st.setdefault("pinned", [])
    st.setdefault("seen", [])
    st.setdefault("days", [])
    st.setdefault("feedback", {"liked": [], "hidden": [], "hiddenSources": []})

    seen = set(st["seen"])
    pinned_fps = {fp(p["url"]) for p in st["pinned"]}
    pinned_urls = {p["url"] for p in st["pinned"]}

    fresh, deduped, newpins = [], 0, 0
    for it in items:
        f = fp(it["url"])
        if it.pop("pin", False):
            if it["url"] not in pinned_urls:
                st["pinned"].append({k: it.get(k, "") for k in
                                     ("title", "url", "source", "topic")})
                pinned_urls.add(it["url"]); pinned_fps.add(f); newpins += 1
            continue
        if f in seen or f in pinned_fps:
            deduped += 1
            continue
        seen.add(f)
        it.setdefault("thumb", "")
        fresh.append(it)

    st["days"].insert(0, {"date": date, "items": fresh})

    trimmed = 0
    if len(st["days"]) > KEEP_DAYS:
        for d in st["days"][KEEP_DAYS:]:
            trimmed += len(d.get("items", []))
        st["days"] = st["days"][:KEEP_DAYS]

    st["seen"] = sorted(seen)
    return {"added": len(fresh), "deduped": deduped, "pinned_added": newpins,
            "trimmed": trimmed, "days_on_page": len(st["days"]),
            "seen_total": len(st["seen"])}

# ---------- ページを組み立てる ----------

def render(st):
    body = open(TEMPLATE_FILE, encoding="utf-8").read()
    if body.count("__TEMPLATE__") != 1 or body.count("__STATE__") != 1:
        raise SystemExit("テンプレートのプレースホルダが1つずつではありません")
    full = ('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "</head><body>" + body + "</body></html>")
    b64 = base64.b64encode(full.encode("utf-8")).decode("ascii")
    return body.replace("__TEMPLATE__", b64).replace(
        "__STATE__", json.dumps(st, ensure_ascii=False))

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="現在のアーティファクトHTML（省略で新規）")
    ap.add_argument("--state", help="状態JSONを直接渡す場合")
    ap.add_argument("--new", required=True, help="今日の記事JSON")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--updated", help="最終更新の表示（既定: dateT07:00:00+09:00）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.state:
        st = json.load(open(a.state, encoding="utf-8"))
    elif a.page:
        st = state_from_page(a.page)
    else:
        st = blank_state()

    items = json.load(open(a.new, encoding="utf-8"))
    report = add_day(st, a.date, items)
    st["updated"] = a.updated or f"{a.date}T07:00:00+09:00"

    html = render(st)
    open(a.out, "w", encoding="utf-8").write(html)
    report["out_bytes"] = len(html.encode())
    print(json.dumps(report, ensure_ascii=False))

if __name__ == "__main__":
    main()
