#!/usr/bin/env python3
"""
Volvo V90 Cross Country 中古車スクレイパー
対象サイト: カーセンサー / グーネット / MOTA (autoc-one.jp)
"""

import os
import json
import time
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ─────────────────────────────
# 設定
# ─────────────────────────────
NTFY_TOPIC       = os.environ.get("NTFY_TOPIC", "")          # 例: volvo-tracker-yosuke（推測されにくい名前にする）
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "")   # 例: https://yourname.github.io/volvo-tracker/

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
    # "15.1万km" → 151000 / "7万km" → 70000
    m = re.search(r"([\d.]+)\s*万\s*km", text)
    if m:
        return int(float(m.group(1)) * 10_000)
    m = re.search(r"([\d,]+)\s*km", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_price_man(text: str):
    # "271\n万円" や "271万円" → 271
    m = re.search(r"([\d.]+)\s*万円", text.replace("\n", ""))
    return int(float(m.group(1))) if m else None


# ─────────────────────────────
# カーセンサー
# ─────────────────────────────
CARSENSOR_BASE = "https://www.carsensor.net/usedcar/bVO/s043/low_totalPrice/index.html"


def scrape_carsensor() -> list[dict]:
    listings = []
    session = requests.Session()
    session.headers.update(HEADERS)

    page = 1
    while True:
        if page == 1:
            url = CARSENSOR_BASE
        else:
            url = CARSENSOR_BASE.replace(
                "index.html", f"CS120X{page:02d}0001_index.html"
            )

        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        items = soup.select(".cassetteMain")
        if not items:
            break

        for item in items:
            # ── タイトル（グレード名）
            car_info = item.select_one(".cassetteMain__carInfoContainer")
            raw_text = car_info.get_text(" ", strip=True) if car_info else ""
            title_m = re.search(r"V90クロスカントリー[^\n]{0,80}", raw_text)
            title = title_m.group(0).strip() if title_m else raw_text[:80]

            # ── D4のみ（T5/T6/B5/PHEVは除外）
            if "D4" not in title:
                continue

            # ── 年式・走行距離
            year = distance_km = None
            for spec in item.select(".specList__detailBox"):
                t = spec.get_text(strip=True)
                if "年式" in t:
                    year = parse_year(t)
                elif "走行距離" in t:
                    distance_km = parse_distance_km(t)

            # ── 支払総額（.totalPrice__mainPriceNum を直接取得）
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

            # ── 詳細リンク
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

        next_btn = soup.select_one(".pager__item--next:not(.pager__item--disabled)")
        if not next_btn or page >= 10:
            break
        page += 1
        time.sleep(1.5)

    return listings


# ─────────────────────────────
# グーネット
# ─────────────────────────────
GOONET_URL = "https://www.goo-net.com/php/search/summary.php"

GOONET_PARAMS = {
    "maker_cd":       "4010",
    "car_cd":         "40102508",
    "pref_c":         "08,09,10,11,12,13,14,22,07,15,20,19",
    "car_grade_cd":   (
        "40102508|86,40102508|76,40102508|89,40102508|73,"
        "40102508|113,40102508|129,40102508|69,40102508|79,"
        "40102508|66,40102508|36,40102508|33"
    ),
    "model_select_cd": (
        "40102508_86_43,40102508_86_46,40102508_76_46,40102508_76_43,"
        "40102508_89_43,40102508_89_46,40102508_73_43,40102508_73_46,"
        "40102508_113_63,40102508_113_33,40102508_129_63,"
        "40102508_69_36,40102508_69_39,40102508_79_36,"
        "40102508_66_36,40102508_66_39,40102508_36_29,"
        "40102508_36_26,40102508_33_26"
    ),
    "price1":        "",
    "price2":        "400",
    "car_price":     "0",
    "total_payment": "1",
    "distance1":     "",
    "distance2":     "70000",
    "nenshiki":      "",
    "nen1":          "",
    "nen2":          "",
    "color":         "",
    "genre":         "",
    "mission":       "",
    "nenryo":        "",
    "baitai":        "goo",
    "jititai_id":    "",
    "grade_cd_list": "",
    "imp_flg":       "",
    "net_mitsumori": "",
    "wd":            "",
    "exhaust1":      "",
    "exhaust2":      "",
}


def scrape_goonet() -> list[dict]:
    listings = []
    session = requests.Session()
    session.headers.update(HEADERS)

    page = 1
    while True:
        params = {**GOONET_PARAMS, "offset": (page - 1) * 10}
        resp = session.post(GOONET_URL, data=params, timeout=30)
        resp.raise_for_status()

        html = resp.content.decode("euc-jp", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        items = soup.select(".box_item_detail")
        if not items:
            break

        for item in items:
            heading = item.select_one(".heading_inner")
            title = heading.get_text(" ", strip=True)[:100] if heading else "Unknown"

            # ── D4のみ（T5/T6/B5/PHEVは除外）
            if "D4" not in title:
                continue

            dw = item.select_one(".data-wrapper")
            dw_text = dw.get_text(" ", strip=True) if dw else ""
            dw_text = dw_text.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))

            year_m   = re.search(r"年式\s*(\d{4})\s*年", dw_text)
            dist_m   = re.search(r"走行距離\s*([\d.]+)\s*万\s*km", dw_text)

            year        = int(year_m.group(1)) if year_m else None
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

        next_link = soup.select_one(".pager_next a, .pager a.next")
        if not next_link or page >= 10:
            break
        page += 1
        time.sleep(1.5)

    return listings


# ─────────────────────────────
# MOTA (autoc-one.jp)
# ─────────────────────────────
MOTA_URL = (
    "https://autoc-one.jp/used/searchv2/"
    "?makerFullCodes=VO"
    "&modelFullCodes=VO_S043"
    "&grades=VO_S043_F001_K010*VO_S043_F001_K009"
    "*VO_S043_F001_K007*VO_S043_F001_K008*VO_S043_F001_K006"
    "&sort=6a"
)


def scrape_mota() -> list[dict]:
    listings = []
    session = requests.Session()

    mota_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    session.headers.update(mota_headers)

    try:
        # トップページを先に訪問してクッキーを取得
        try:
            session.get("https://autoc-one.jp/", timeout=15)
            time.sleep(1.5)
        except Exception:
            pass

        # 検索ページをReferer付きで取得
        session.headers.update({
            "Referer": "https://autoc-one.jp/",
            "Sec-Fetch-Site": "same-origin",
        })
        resp = session.get(MOTA_URL, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        items = soup.select("li.usdcar_lst")
        print(f"  {len(items)} items found")

        for item in items:
            carname_el = item.select_one(".carname")
            title = carname_el.get_text(" ", strip=True) if carname_el else ""
            title = title[:100]

            # ── D4のみ
            if title and "D4" not in title:
                continue

            year = distance_km = None
            labels = item.select(".mdt")
            values = item.select(".mdd")
            for lbl, val in zip(labels, values):
                lbl_text = lbl.get_text(strip=True)
                val_text = val.get_text(strip=True).translate(
                    str.maketrans("０１２３４５６７８９．", "0123456789.")
                )
                if lbl_text == "年式":
                    year = parse_year(val_text)
                elif lbl_text == "走行":
                    distance_km = parse_distance_km(val_text)

            price_box = item.select_one(".price_box")
            price_text = price_box.get_text(" ", strip=True) if price_box else ""
            price_text = price_text.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
            total_m = re.search(r"支払総額\s*([\d.]+)\s*万円", price_text)
            if total_m:
                price_man = int(float(total_m.group(1)))
            else:
                price_man = parse_price_man(price_text)

            link_el = item.select_one('a[href*="/used/detail/"]')
            if link_el:
                href = link_el.get("href", "")
                link = href if href.startswith("http") else "https://autoc-one.jp" + href
            else:
                link = ""

            if year and distance_km:
                listings.append({
                    "source": "mota",
                    "title": title,
                    "year": year,
                    "distance_km": distance_km,
                    "price_man": price_man,
                    "url": link,
                    "fingerprint": make_fingerprint(year, distance_km),
                    "scraped_at": datetime.now().isoformat(),
                })

    except Exception as e:
        print(f"  MOTA error: {e}")

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
    title = f"🚗 V90 CC 新着 {count}件"

    lines = []
    for l in new_listings[:5]:
        dist  = f"{l['distance_km'] // 10_000:.1f}万km" if l["distance_km"] else ""
        price = f"{l['price_man']}万円" if l["price_man"] else "価格不明"
        srcs  = "/".join(l.get("sources", {l["source"]: ""}).keys())
        lines.append(f"{l['year']}年 {dist} {price} [{srcs}]")
    if count > 5:
        lines.append(f"…他{count - 5}件")

    headers = {
        "Title":    title,
        "Priority": "default",
        "Tags":     "car",
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

    all_raw: list[dict] = []

    print("▶ カーセンサー")
    try:
        cs = scrape_carsensor()
        all_raw.extend(cs)
        print(f"  {len(cs)} listings")
    except Exception as e:
        print(f"  ERROR: {e}")

    print("▶ グーネット")
    try:
        goo = scrape_goonet()
        all_raw.extend(goo)
        print(f"  {len(goo)} listings")
    except Exception as e:
        print(f"  ERROR: {e}")

    print("▶ MOTA")
    try:
        mota = scrape_mota()
        all_raw.extend(mota)
        print(f"  {len(mota)} listings")
    except Exception as e:
        print(f"  ERROR: {e}")

    merged = merge_listings(all_raw)
    print(f"▶ マージ後: {len(merged)} 件")

    seen_list: list[str] = load_json(SEEN_FILE, [])
    seen: set[str]       = set(seen_list)
    first_run            = len(seen) == 0

    new_listings = [l for l in merged if l["fingerprint"] not in seen]
    print(f"▶ 新着: {len(new_listings)} 件{'（初回実行のため通知なし）' if first_run else ''}")

    save_json(DATA_FILE, {
        "updated_at": datetime.now().isoformat(),
        "total":      len(merged),
        "listings":   merged,
    })

    seen.update(l["fingerprint"] for l in merged)
    save_json(SEEN_FILE, sorted(seen))

    if new_listings and not first_run:
        send_ntfy(new_listings)

    print(f"=== Done: {datetime.now().isoformat()} ===")


if __name__ == "__main__":
    main()
