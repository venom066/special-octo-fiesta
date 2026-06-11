# Agent Handoff — 中古車ウォッチャー

## ユーザーとの作業ルール（必読）

### ファイルの渡し方
**`mcp__cowork__present_files` でファイルカードを出す。これだけ。**

- ファイルを編集したら最後に必ずこれを呼ぶ
- Chromeタブへのinject・ローカルサーバー・スクリプト実行は不要・禁止
- ユーザーはカードからファイルを開いてGitHubに貼る

### 編集スタイル
- **ファイル全体を書き直さない。変わる部分だけ `Edit` で差し替える。**
- 変更箇所が複数あっても、セクションごとに個別のEditで対応する
- 編集後は `python3 -m py_compile` や `node --check` で構文チェックする
- 回答は簡潔に。説明より手を動かす。

### ツール制約
- **computer-use（`mcp__computer-use__*`）は使わない**
- ブラウザ操作が必要なときは `mcp__Claude_in_Chrome__*` のみ

### モデルについて
- 現在動いているのは **claude-sonnet-4-6**
- Sonnetは速さとコーディング精度のバランス型。このプロジェクトの「局所修正」タスクに向いている
- Opusは複雑な推論・長文分析向け。このプロジェクトでは不要

---

## プロジェクト概要

- **リポジトリ**: `venom066/special-octo-fiesta` (GitHub Pages)
- **構成**: `index.html` (フロントエンド) + `scraper/scrape.py` (スクレイパー) + `data/data.json` (データ) + `config.json` (ウォッチ設定)
- **スクレイプ対象**: カーセンサー / グーネット
- **通知**: ntfy.sh

### config.json の watches 構造
```json
{
  "watches": [
    {
      "name": "V60 B(MHEV)",
      "carsensor_url": "...",
      "goonet_url": "..."
    }
  ]
}
```

### data.json の listings 構造
```json
{
  "source": "carsensor",
  "title": "...",
  "year": 2021,
  "distance_km": 31000,
  "price_man": 279,
  "url": "...",
  "fingerprint": "carsensor_AU7077055949",
  "watch_name": "V60 B(MHEV)",
  "scraped_at": "...",
  "sources": { "carsensor": "...", "goonet": "..." }
}
```

### localStorage キー（index.html）
- `usedcar_favorites` — お気に入りfingerprint Set
- `usedcar_seen_cache` — 表示済みキャッシュ `{fp: listing}`
- `usedcar_dismissed` — 非表示fingerprint Set
- `usedcar_version` — ストレージ移行バージョン（現在 `"2"`）

---

## 作業ファイルの場所

編集中のファイルは outputs フォルダにある：
- `scrape_fixed.py` → GitHubの `scraper/scrape.py` に反映するもの
- `index.html` → GitHubの `index.html` に反映するもの

---

## 現在のコードの状態（実装済み）

### scrape.py
- GooNetの価格セレクタ: `.hontai-price .num-red` → fallback `.hontai-price .num`
- ASK（要相談）= 0円扱いを除外
- **ID制fingerprint**: `extract_listing_id(url, source)` でURLからID抽出、`fingerprint = "{source}_{id}"`
- **`is_same_car(a, b)`**: 年式一致 + 距離±1,000km + 価格±1万 で同一車両判定
- **`merge_listings()`**: watch内でカーセンサー×グーネットを突合してsourcesをマージ
- seen.json が旧format（`年式_距離`）のみの場合は `first_run=True` 扱い（通知スパム防止）

### index.html
- ASK=0 の表示修正
- アクティブカードに ✕（dismiss）ボタン追加
- ロード時に dismissed をフィルター（再スクレイプ後も非表示維持）
- `migrateStorage()`: バージョン不一致時に seen_cache・dismissed・favs をクリア
- 売却済み検知: ID制に移行したため renumbered チェックは削除済み

### scrape.py の主要関数
```python
extract_listing_id(url, source) -> str
make_fingerprint(source, listing_id) -> str
is_new_format_fp(fp) -> bool
is_same_car(a, b) -> bool
merge_listings(all_listings) -> list[dict]
scrape_carsensor(base_url, watch_name) -> list[dict]
scrape_goonet(base_url, watch_name) -> list[dict]
send_ntfy(new_listings) -> None
main() -> None
```
