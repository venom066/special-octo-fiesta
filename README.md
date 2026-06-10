# V90 Cross Country 中古車ウォッチャー

Volvo V90クロスカントリー の新着中古車を自動検索し、iPhoneに通知するシステムです。

- **スクレイプ対象**: カーセンサー / グーネット / MOTA
- **実行間隔**: 30分ごと（GitHub Actions）
- **UI**: GitHub Pages で静的ページを配信（iPhone/Macからアクセス可）
- **通知**: Pushover アプリでiPhoneにプッシュ通知

---

## セットアップ手順

### 1. GitHubリポジトリを作成

1. [github.com](https://github.com) でアカウントを作成（または既存アカウントを使用）
2. 「New repository」をクリック
3. Repository name: `volvo-tracker`（任意）
4. **Public** を選択（Private だとActions無料枠に制限あり）
5. 「Create repository」

### 2. ファイルをアップロード

このフォルダの中身をすべてリポジトリにアップロードします。

```
volvo-tracker/
├── .github/workflows/scrape.yml
├── scraper/scrape.py
├── data/
│   ├── data.json
│   └── seen.json
├── index.html
├── requirements.txt
└── README.md
```

**方法A（GitHub Web UI）**: 「Add file」→「Upload files」で全ファイルをドラッグ＆ドロップ

**方法B（git コマンド）**:
```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/あなたのユーザー名/volvo-tracker.git
git push -u origin main
```

### 3. GitHub Pages を有効化

1. リポジトリの「Settings」タブ
2. 左メニュー「Pages」
3. Source: **Deploy from a branch**
4. Branch: **main** / **/ (root)**
5. Save

数分後に `https://あなたのユーザー名.github.io/volvo-tracker/` でアクセス可能になります。

### 4. ntfy をセットアップ（iPhone通知・無料）

1. iPhoneに [ntfy アプリ](https://apps.apple.com/jp/app/ntfy/id1625378347) をインストール（無料）
2. アプリを開いて「+」→ トピック名を入力して購読（例: `volvo-tracker-yosuke`）
   - トピック名は**他人に推測されにくい文字列**にする（URLが公開されているため）
   - アカウント登録不要

### 5. GitHub Secrets を設定

1. リポジトリ「Settings」→「Secrets and variables」→「Actions」
2. 「New repository secret」で以下の2つを追加:

| Name | Value |
|------|-------|
| `NTFY_TOPIC` | 手順4で決めたトピック名（例: `volvo-tracker-yosuke`） |
| `GITHUB_PAGES_URL` | `https://あなたのユーザー名.github.io/volvo-tracker/` |

### 6. 動作確認

1. リポジトリの「Actions」タブ
2. 「Scrape V90 Cross Country」ワークフロー
3. 「Run workflow」→「Run workflow」で手動実行
4. ログにエラーがなければOK
5. `data/data.json` が更新され、iPhoneに通知が届くはず（2回目の実行から）

---

## 仕組み

```
GitHub Actions (30分ごと)
    │
    ├─ カーセンサー scrape (requests + BeautifulSoup)
    ├─ グーネット scrape (requests + BeautifulSoup, EUC-JP)
    └─ MOTA (autoc-one.jp) scrape (requests + BeautifulSoup)
    │
    ├─ フィンガープリント照合 (年式 + 走行距離)
    ├─ 新着検出 → Pushover 通知
    └─ data/data.json, data/seen.json をコミット
         │
         └─ GitHub Pages が index.html + data.json を配信
```

## 検索条件

| サイト | 条件 |
|--------|------|
| カーセンサー | V90クロスカントリー 全国・全グレード |
| グーネット | V90 D4/T6/PHEVグレード、関東＋隣接県、400万以下、7万km以下 |
| MOTA | V90クロスカントリー 全国 |

## グーネットの検索条件を変更したい場合

`scraper/scrape.py` の `GOONET_PARAMS` を編集してください。
パラメータはブラウザの開発者ツール（F12）→ Network タブで確認できます。

---

## トラブルシューティング

**Actions が実行されない**
- Public リポジトリか確認
- Settings → Actions → General → 「Allow all actions」が有効か確認

**通知が来ない**
- ntfy アプリでトピックを購読済みか確認
- Secrets の `NTFY_TOPIC` がアプリのトピック名と一致しているか確認
- Actions ログで「ntfy status: 200」が表示されているか確認

**MOTAのデータが取れない**
- URLが変わった場合は `scraper/scrape.py` の `MOTA_URL` を修正（autoc-one.jp）
- Actions ログで「N items found」の件数を確認
