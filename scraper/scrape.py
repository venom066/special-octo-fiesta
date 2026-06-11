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
def extract_listing_id(url: str, source: str) -> str:
    """URLからサイト固有のリスティングIDを抽出"""
    if source == "carsensor":
        # /usedcar/detail/AU7077055949/
        m = re.search(r"/usedcar/detail/([^/?#]+)", url)
        return m.group(1) if m else url
    elif source == "goonet":
        # /usedcar/spread/goo/{都道府県コード}/{リスティングID}.html
        m = re.search(r"/usedcar/spread/goo/\d+/(\d+)", url)
        if m:
            return m.group(1)
        return url
    return url

def make_fingerprint(source: str, listing_id: str) -> str:
    return f"{source}_{listing_id}"

def is_new_format_fp(fp: str) -> bool:
    return fp.startswith("carsensor_") or fp.startswith("goonet_")

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
def scrape_carsensor(base_url: str, watch_name: str = "") -> list[dict]:
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
                # バッジ類（保証表示など）を除いた純粋な車名部分を取得
                for badge in car_info.select(".badge, .cassetteMain__badges, .cassetteMain__label"):
                    badge.decompose()
                raw = car_info.get_text(" ", strip=True)
                # 既知のノイズ文字列を除去
                for noise in ["保証の種類を表示しています", "保証の種類について", "360° 画像付", "オンライン相談可", "車両品質評価書付", "販売店保証", "ディーラー保証"]:
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

            # ASK（要相談）= 0円扱いを除外
            if price_man == 0:
                price_man = None

            # 詳細リンク
            link_el = item.select_one('a[href*="/usedcar/detail/"]')
            if link_el:
                href = link_el.get("href", "")
                link = href if href.startswith("http") else "https://www.carsensor.net" + href
            else:
                link = ""

            # サムネイル画像URL
            img_el = item.select_one("img.js-lazy")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else None
            if image_url and image_url.startswith("/"):
                image_url = "https://www.carsensor.net" + image_url

            if year and distance_km and link:
                listing_id = extract_listing_id(link, "carsensor")
                listings.append({
                    "source": "carsensor",
                    "title": title,
                    "year": year,
                    "distance_km": distance_km,
                    "price_man": price_man,
                    "url": link,
                    "fingerprint": make_fingerprint("carsensor", listing_id),
                    "watch_name": watch_name,
                    "scraped_at": datetime.now().isoformat(),
                    "image_url": image_url,
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
def scrape_goonet(base_url: str, watch_name: str = "") -> list[dict]:
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

            # 支払総額: .hontai-price .num-red（赤字）→ fallback .hontai-price .num
            price_el = item.select_one(".hontai-price .num-red")
            if not price_el:
                price_el = item.select_one(".hontai-price .num")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price_text = price_text.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
            price_m = re.search(r"([\d.]+)", price_text)
            price_man = int(float(price_m.group(1))) if price_m else None

            # ASK（要相談）= 0円扱いを除外
            if price_man == 0:
                price_man = None

            link_el = item.select_one('a[href*="/usedcar/spread/"]')
            if link_el:
                href = link_el.get("href", "").split("#")[0]
                link = href if href.startswith("http") else "https://www.goo-net.com" + href
            else:
                link = ""

            # サムネイル画像URL（.lazy はアイコン類なので除く）
            img_el = item.select_one("img[onerror]") or next(
                (i for i in item.select("img") if "lazy" not in i.get("class", [])), None
            )
            image_url = None
            if img_el:
                raw = img_el.get("src") or img_el.get("data-original", "")
                if raw and not raw.endswith(("fav_off.png", "fav_on.png")):
                    image_url = raw if raw.startswith("http") else "https://www.goo-net.com" + raw

            if year and distance_km and link:
                listing_id = extract_listing_id(link, "goonet")
                listings.append({
                    "source": "goonet",
                    "title": title,
                    "year": year,
                    "distance_km": distance_km,
                    "price_man": price_man,
                    "url": link,
                    "fingerprint": make_fingerprint("goonet", listing_id),
                    "watch_name": watch_name,
                    "scraped_at": datetime.now().isoformat(),
                    "image_url": image_url,
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
# 同一車両判定・クロスサイト突合
# ─────────────────────────────
def is_same_car(a: dict, b: dict) -> bool:
    """カーセンサー/グーネット間で同一車両かどうかを判定"""
    if a["year"] != b["year"]:
        return False
    if abs(a["distance_km"] - b["distance_km"]) > 1000:
        return False
    # 両方価格あり → ±1万で比較
    if a["price_man"] and b["price_man"]:
        if abs(a["price_man"] - b["price_man"]) > 1:
            return False
    # 片方または両方がnull → 年式・距離だけで突合
    return True

def merge_listings(all_listings: list[dict]) -> list[dict]:
    """
    各listingはID由来のユニークfingerprintを持つ。
    同一watch内でカーセンサー×グーネットの同一車両を突合してsourcesをマージ。
    """
    # watch_name ごとにグループ化
    by_watch: dict[str, list[dict]] = {}
    for l in all_listings:
        by_watch.setdefault(l["watch_name"], []).append(l)

    result = []
    for watch_listings in by_watch.values():
        cs_list  = [l for l in watch_listings if l["source"] == "carsensor"]
        goo_list = [l for l in watch_listings if l["source"] == "goonet"]

        matched_goo: set[int] = set()

        for cs in cs_list:
            merged = {**cs, "sources": {"carsensor": cs["url"]}}
            for i, goo in enumerate(goo_list):
                if i in matched_goo:
                    continue
                if is_same_car(cs, goo):
                    merged["sources"]["goonet"] = goo["url"]
                    # 価格は安い方を採用
                    if goo["price_man"] and (
                        not merged["price_man"]
                        or goo["price_man"] < merged["price_man"]
                    ):
                        merged["price_man"] = goo["price_man"]
                    # 突合の信頼度チェック
                    dist_diff = abs(cs["distance_km"] - goo["distance_km"])
                    price_diff = (
                        abs(cs["price_man"] - goo["price_man"])
                        if cs["price_man"] and goo["price_man"] else None
                    )
                    merged["match_suspicious"] = (
                        dist_diff > 500
                        or price_diff is None
                        or price_diff >= 1
                    )
                    # split用に両IDを記録
                    merged["merged_fps"] = [cs["fingerprint"], goo["fingerprint"]]
                    matched_goo.add(i)
                    break
            result.append(merged)

        # マッチしなかったグーネット単独出品
        for i, goo in enumerate(goo_list):
            if i not in matched_goo:
                result.append({**goo, "sources": {"goonet": goo["url"]}})

    return result

# ─────────────────────────────
FAVORITES_FILE = "data/favorites.json"

def load_favorites() -> set[str]:
    data = load_json(FAVORITES_FILE, [])
    return set(data)

# ntfy.sh 通知
# ─────────────────────────────
def send_ntfy(new_listings: list[dict], price_changed_favs: list[dict] | None = None) -> None:
    if not NTFY_TOPIC:
        print("  NTFY_TOPIC not set — skipping")
        return
    price_changed_favs = price_changed_favs or []
    if not new_listings and not price_changed_favs:
        return

    sections: list[str] = []

    if new_listings:
        count = len(new_listings)
        sections.append(f"【新着 {count}件】")
        for l in new_listings[:5]:
            dist = f"{l['distance_km'] // 10_000:.1f}万km" if l["distance_km"] else ""
            price = f"{l['price_man']}万円" if l["price_man"] else "価格不明"
            srcs = "/".join(l.get("sources", {l["source"]: ""}).keys())
            sections.append(f"{l['year']}年 {dist} {price} [{srcs}] {l['title'][:20]}")
        if count > 5:
            sections.append(f"…他{count - 5}件")

    if price_changed_favs:
        if sections:
            sections.append("")
        sections.append(f"【★値下がり {len(price_changed_favs)}件】")
        for l in price_changed_favs[:5]:
            dist = f"{l['distance_km'] // 10_000:.1f}万km" if l["distance_km"] else ""
            sections.append(f"{l['year']}年 {dist} {l['prev_price_man']}万→{l['price_man']}万円 {l['title'][:20]}")
        if len(price_changed_favs) > 5:
            sections.append(f"…他{len(price_changed_favs) - 5}件")

    parts = []
    if new_listings:
        parts.append(f"新着{len(new_listings)}件")
    if price_changed_favs:
        parts.append(f"★値下がり{len(price_changed_favs)}件")
    title = "中古車 " + " / ".join(parts)
    lines = sections

    payload: dict = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": "\n".join(lines),
        "tags": ["car"],
        "priority": 3,
    }
    if GITHUB_PAGES_URL:
        payload["click"] = GITHUB_PAGES_URL

    try:
        resp = requests.post(
            "https://ntfy.sh",
            json=payload,
            timeout=10,
        )
        print(f"  ntfy status: {resp.status_code}")
    except Exception as e:
        print(f"  ntfy error (skipping): {e}")

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
                cs = scrape_carsensor(cs_url, watch_name=name)
                all_raw.extend(cs)
                print(f"  → {len(cs)} 件")
            except Exception as e:
                print(f"  ERROR: {e}")

        goo_url = watch.get("goonet_url", "")
        if goo_url:
            print("  [グーネット]")
            try:
                goo = scrape_goonet(goo_url, watch_name=name)
                all_raw.extend(goo)
                print(f"  → {len(goo)} 件")
            except Exception as e:
                print(f"  ERROR: {e}")

    merged = merge_listings(all_raw)
    print(f"\n▶ マージ後: {len(merged)} 件")

    # 前回データとの価格比較
    prev_data = load_json(DATA_FILE, {})
    prev_prices: dict[str, int | None] = {
        l["fingerprint"]: l.get("price_man")
        for l in prev_data.get("listings", [])
    }
    for l in merged:
        prev = prev_prices.get(l["fingerprint"])
        if prev is not None and l.get("price_man") is not None and prev != l["price_man"]:
            l["prev_price_man"] = prev

    seen_list: list[str] = load_json(SEEN_FILE, [])
    seen: set[str] = set(seen_list)
    # seen.jsonが空 or 旧format（年式_距離）のみ → 移行初回扱いで通知しない
    first_run = len(seen) == 0 or not any(is_new_format_fp(fp) for fp in seen)

    new_listings = [l for l in merged if l["fingerprint"] not in seen]
    print(f"▶ 新着: {len(new_listings)} 件{'（初回実行のため通知なし）' if first_run else ''}")

    # お気に入り×値下がりの通知対象
    favorites = load_favorites()
    price_changed_favs = [
        l for l in merged
        if "prev_price_man" in l
        and l.get("price_man") is not None
        and l["prev_price_man"] > l["price_man"]
        and l["fingerprint"] in favorites
        and not first_run
    ]
    if price_changed_favs:
        print(f"▶ ★値下がり: {len(price_changed_favs)} 件")

    save_json(DATA_FILE, {
        "updated_at": datetime.now().isoformat(),
        "total": len(merged),
        "listings": merged,
    })

    seen.update(l["fingerprint"] for l in merged)
    save_json(SEEN_FILE, sorted(seen))

    if (new_listings or price_changed_favs) and not first_run:
        send_ntfy(new_listings, price_changed_favs)

    print(f"=== Done: {datetime.now().isoformat()} ===")

if __name__ == "__main__":
    main()
