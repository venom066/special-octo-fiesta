#!/usr/bin/env python3
"""
汎用中古車スクレイパー
設定: config.json でカーセンサー/グーネットの検索URLを指定するだけ
"""

import os
import json
import time
import re
import requests
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup

# ─────────────────────────────
# 設定
# ─────────────────────────────
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "")

CONFIG_FILE = "config.json"
DATA_FILE = "data/data.json"
SEEN_FILE = "data/seen.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─────────────────────────────
# ユーティリティ
# ─────────────────────────────
def make_fingerprint(year: int, distance_km: int) -> str:
    return f"{year}_{distance_km}"

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def parse_year(text: str):
    m = re.search(r"(\d{4})", text)
    return int(m.group(1)) if m else None

def parse_distance_km(text: str):
    m = re.search(r"([\d.]+)\s*万\s*km", text)
    if m:
        return int(float(m.group(1)) * 10_000)
    m = re.search(r"([\d,]+)\s*km", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None

def parse_price_man(text: str):
    m = re.search(r"([\d.]+)\s*万円", text.replace("\n", ""))
    return int(float(m.group(1))) if m else None

def url_set_param(url: str, key: str, value: str) -> str:
    """URLの特定パラメータを書き換えて返す"""
    parsed = urlparse(url)
    params = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    params[key] = value
    return urlunparse(parsed._replace(query=urlencode(params)))

# ─────────────────────────────
# カーセンサー
# ─────────────────────────────

# カーセンサーのタイトルに混入するノイズ文字列
_CS_NOISE = [
    "保証の種類を表示しています", "保証の種類について",
    "360° 画像付", "オンライン相談可", "車両品質評価書付",
    "販売店保証", "ディーラー保証",
]

def scrape_carsensor(base_url: str) -> list[dict]:
    listings = []
    session = requests.Session()
    session.headers.update(HEADERS)

    url = base_url
    page = 1

    while True:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        items = soup.select(".cassetteMain")
        if not items:
            break

        for item in items:
            # タイトル（バッジ・注記テキストを除去）
            car_info = item.select_one(".cassetteMain__carInfoContainer")
            if car_info:
                for badge in car_info.select(".badge, .cassetteMain__badges, .cassetteMain__label"):
                    badge.decompose()
                raw = car_info.get_text(" ", strip=True)
                for noise in _CS_NOISE:
                    raw = raw.replace(noise, "")
                title = " ".join(raw.split())[:100]
            else:
                title = ""

            # 年式・走行距離
            year = distance_km = None
            for spec in item.select(".specList__detailBox"):
                t = spec.get_text(strip=True)
                if "年式" in t:
                    year = parse_year(t)
                elif "走行距離" in t:
                    distance_km = parse_distance_km(t)

            # 支払総額
            num_el = item.select_one(".totalPrice__mainPriceNum")
            if num_el:
                try:
                    price_man = int(float(num_el.get_text(strip=True).replace(",", "")))
                except ValueError:
                    price_man = None
            else:
                price_el = item.select_one(".cassetteMain__priceInfo")
                price_text = price_el.get_text(" ", strip=True) if price_el else ""
                price_man = parse_price_man(price_text)

            # 詳細リンク
            link_el = item.select_one('a[href*="/usedcar/detail/"]')
            if link_el:
                href = link_el.get("href", "")
                link = href if href.startswith("http") else "https://www.carsensor.net" + href
            else:
                link = ""

            if year and distance_km:
                listings.append({
                    "source": "carsensor",
                    "title": title,
                    "year": year,
                    "distance_km": distance_km,
                    "price_man": price_man,
                    "url": link,
                    "fingerprint": make_fingerprint(year, distance_km),
                    "scraped_at": datetime.now().isoformat(),
                })

        # 次ページ: 「次へ」リンクのhrefを直接使う
        next_btn = soup.select_one(".pager__item--next:not(.pager__item--disabled) a")
        if not next_btn or page >= 10:
            break

        href = next_btn.get("href", "")
        url = href if href.startswith("http") else "https://www.carsensor.net" + href
        page += 1
        time.sleep(1.5)

    return listings

# ─────────────────────────────
# グーネット（GET対応）
# ─────────────────────────────
def scrape_goonet(base_url: str) -> list[dict]:
    listings = []
    session = requests.Session()
    session.headers.update(HEADERS)

    # offset=0 から開始、limit は URL に含まれていれば使う（デフォルト50）
    parsed_base = urlparse(base_url)
    base_params = {k: v[0] for k, v in parse_qs(parsed_base.query, keep_blank_values=True).items()}
    limit = int(base_params.get("limit", "50"))

    offset = 0
    page = 1

    while True:
        params = {**base_params, "offset": str(offset)}
        url = urlunparse(parsed_base._replace(query=urlencode(params)))

        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        html = resp.content.decode("euc-jp", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        items = soup.select(".box_item_detail")
        if not items:
            break

        for item in items:
            heading = item.select_one(".heading_inner")
            title = heading.get_text(" ", strip=True)[:100] if heading else "Unknown"

            dw = item.select_one(".data-wrapper")
            dw_text = dw.get_text(" ", strip=True) if dw else ""
            dw_text = dw_text.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))

            year_m = re.search(r"年式\s*(\d{4})\s*年", dw_text)
            dist_m = re.search(r"走行距離\s*([\d.]+)\s*万\s*km", dw_text)

            year = int(year_m.group(1)) if year_m else None
            distance_km = int(float(dist_m.group(1)) * 10_000) if dist_m else None

            price_el = item.select_one(".total_payment .num")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price_text = price_text.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
            price_m = re.search(r"([\d.]+)", price_text)
            price_man = int(float(price_m.group(1))) if price_m else None

            link_el = item.select_one('a[href*="/usedcar/spread/"]')
            if link_el:
                href = link_el.get("href", "").split("#")[0]
                link = href if href.startswith("http") else "https://www.goo-net.com" + href
            else:
                link = ""

            if year and distance_km:
                listings.append({
                    "source": "goonet",
                    "title": title,
                    "year": year,
                    "distance_km": distance_km,
                    "price_man": price_man,
                    "url": link,
                    "fingerprint": make_fingerprint(year, distance_km),
                    "scraped_at": datetime.now().isoformat(),
                })

        # 次ページ確認
        next_link = soup.select_one(".pager_next a, .pager a.next")
        if not next_link or page >= 10:
            break

        offset += limit
        page += 1
        time.sleep(1.5)

    return listings

# ─────────────────────────────
# 重複マージ
# ─────────────────────────────
def merge_listings(all_listings: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for listing in all_listings:
        fp = listing["fingerprint"]
        if fp not in merged:
            merged[fp] = {
                **listing,
                "sources": {listing["source"]: listing["url"]},
            }
        else:
            merged[fp]["sources"][listing["source"]] = listing["url"]
            if listing["price_man"] and (
                not merged[fp]["price_man"]
                or listing["price_man"] < merged[fp]["price_man"]
            ):
                merged[fp]["price_man"] = listing["price_man"]
    return list(merged.values())

# ─────────────────────────────
# ntfy.sh 通知
# ─────────────────────────────
def send_ntfy(new_listings: list[dict]) -> None:
    if not NTFY_TOPIC:
        print("  NTFY_TOPIC not set — skipping")
        return
    if not new_listings:
        return

    count = len(new_listings)
    title = f"🚗 中古車 新着 {count}件"

    lines = []
    for l in new_listings[:5]:
        dist = f"{l['distance_km'] // 10_000:.1f}万km" if l["distance_km"] else ""
        price = f"{l['price_man']}万円" if l["price_man"] else "価格不明"
        srcs = "/".join(l.get("sources", {l["source"]: ""}).keys())
        lines.append(f"{l['year']}年 {dist} {price} [{srcs}] {l['title'][:20]}")
    if count > 5:
        lines.append(f"…他{count - 5}件")

    headers = {
        "Title": title,
        "Priority": "default",
        "Tags": "car",
    }
    if GITHUB_PAGES_URL:
        headers["Click"] = GITHUB_PAGES_URL

    resp = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data="\n".join(lines).encode("utf-8"),
        headers=headers,
        timeout=10,
    )
    print(f"  ntfy status: {resp.status_code}")

# ─────────────────────────────
# メイン
# ─────────────────────────────
def main() -> None:
    print(f"=== Scrape started: {datetime.now().isoformat()} ===")

    config = load_json(CONFIG_FILE, {"watches": []})
    watches = config.get("watches", [])

    if not watches:
        print("config.json に watches が設定されていません")
        return

    all_raw: list[dict] = []

    for watch in watches:
        name = watch.get("name", "Unknown")
        print(f"\n▶ {name}")

        cs_url = watch.get("carsensor_url", "")
        if cs_url:
            print("  [カーセンサー]")
            try:
                cs = scrape_carsensor(cs_url)
                all_raw.extend(cs)
                print(f"  → {len(cs)} 件")
            except Exception as e:
                print(f"  ERROR: {e}")

        goo_url = watch.get("goonet_url", "")
        if goo_url:
            print("  [グーネット]")
            try:
                goo = scrape_goonet(goo_url)
                all_raw.extend(goo)
                print(f"  → {len(goo)} 件")
            except Exception as e:
                print(f"  ERROR: {e}")

    merged = merge_listings(all_raw)
    print(f"\n▶ マージ後: {len(merged)} 件")

    seen_list: list[str] = load_json(SEEN_FILE, [])
    seen: set[str] = set(seen_list)
    first_run = len(seen) == 0

    new_listings = [l for l in merged if l["fingerprint"] not in seen]
    print(f"▶ 新着: {len(new_listings)} 件{'（初回実行のため通知なし）' if first_run else ''}")

    save_json(DATA_FILE, {
        "updated_at": datetime.now().isoformat(),
        "total": len(merged),
        "listings": merged,
    })

    seen.update(l["fingerprint"] for l in merged)
    save_json(SEEN_FILE, sorted(seen))

    if new_listings and not first_run:
        send_ntfy(new_listings)

    print(f"=== Done: {datetime.now().isoformat()} ===")

if __name__ == "__main__":
    main()
