# Microsoft 365 (Graph API) 連携セットアップガイド

本ガイドは、`weekly-task-scheduler` スキルが Outlook Calendar（予定表）および Microsoft To Do（タスク）と直接通信するための認証手順を説明します。

---

## 1. 連携の仕組み

本スキルは、Microsoft 公式の **Microsoft Graph API** を使用します。
認証方式として、ブラウザまたは端末のコード入力で対話的に認可できる **Device Code Flow (デバイスコード認証)** または **Public Client 認証** を採用しています。

### 必要なアクセス許可 (スコープ)
- `Calendars.ReadWrite`: Outlook カレンダーの既存予定の取得および作業枠イベントの登録
- `Tasks.ReadWrite`: Microsoft To Do のタスク一覧取得および期日・完了状態の更新
- `offline_access`: トークンの自動更新（次回以降の再ログイン不要）

---

## 2. 初回セットアップ手順

### オプション A: 組織の Azure AD (Microsoft Entra ID) アプリを使用する場合 (推奨)
1. [Microsoft Entra 管理センター](https://entra.microsoft.com/) にサインイン。
2. **「ID」 > 「アプリケーション」 > 「アプリの登録」 > 「新規登録」** をクリック。
   - 名前: `Antigravity Weekly Task Scheduler`
   - サポートされているアカウントの種類: `この組織ディレクトリのみに含まれるアカウント (シングル テナント)` または `マルチテナント`
3. 登録後、**「認証」** メニューを開く:
   - 「プラットフォームを追加」 > **「モバイル アプリケーションとデスクトップ アプリケーション」** を選択。
   - リダイレクト URI に `https://login.microsoftonline.com/common/oauth2/nativeclient` をチェック。
   - 「パブリック クライアントのフローを許可する」（Device Flow 有効化）を **「はい」** に設定して保存。
4. **「API のアクセス許可」** メニューを開く:
   - 「アクセス許可の追加」 > **「Microsoft Graph」** > **「委任されたアクセス許可」**
   - 以下の3つを追加:
     - `Calendars.ReadWrite`
     - `Tasks.ReadWrite`
     - `User.Read`
5. **クライアント ID** を確認し、環境変数または設定ファイルに記述:
   - `M365_CLIENT_ID`: 作成したアプリの「アプリケーション (クライアント) ID」
   - `M365_TENANT_ID`: 組織の「ディレクトリ (テナント) ID」 (個人の場合は `common`)

---

## 3. スクリプト初回実行時の認証フロー

1. エージェントまたはターミナルから `m365_client.py --login` を実行します。
2. 画面に以下のような案内が表示されます:
   ```text
   To sign in, use a web browser to open the page https://microsoft.com/devicelogin
   and enter the code: ABC123XYZ to authenticate.
   ```
3. ブラウザで URL を開き、表示されたコードを入力してログイン・アクセス許可を承認します。
4. 認証が完了すると、トークンがローカルの `~/.m365_token_cache.bin` に暗号化保存され、以降は自動的にトークンが更新されます。

---

## 4. フォールバック（API未設定時の利用）

Microsoft 365 の API 権限が制限されている環境でも即座にスキルを利用できるよう、以下のフォールバック機構を備えています:
- **タスク入力**: `templates/task_input_fallback.md` に直接タスクを記述または貼り付け。
- **カレンダー出力**: 登録用 `.ics` ファイル（iCalendar形式）を出力し、Outlookでダブルクリックしてワンクリック一括取り込み。
