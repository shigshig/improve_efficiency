# Microsoft Copilot Studio 適用・展開ガイド

本ガイドは、作成した `weekly-task-scheduler` のスケジューリングルール・機能を **Microsoft Copilot Studio** に適用し、Microsoft Teams や Outlook から利用できるようにする完全手順書です。

---

## 1. 前提条件と利用環境

- **ライセンス**: Microsoft 365 Copilot ライセンス、または Microsoft Copilot Studio スタンドアロン/試用ライセンス
- **対象プラットフォーム**: Microsoft Teams、Outlook (Web/デスクトップ)、Microsoft 365 Copilot Chat
- **使用する資産**:
  - システムプロンプト: [copilot_agent_instruction.md](./copilot_agent_instruction.md)

---

## 2. Copilot Studio でのエージェント作成手順

### ステップ 1: 新規エージェントの作成
1. ブラウザで [Microsoft Copilot Studio](https://copilotstudio.microsoft.com/) にアクセスします。
2. 左メニューの **「エージェント (Agents)」** を選択し、**「+ 作成 (Create)」** をクリックします。
3. **「エージェント名」** に以下を入力します：
   - 名前: `週次タスク・スケジュール最適化エージェント`
   - 説明: `金曜17:30までに翌週のOutlook予定表とTo Doタスクを整理し、午前集中・定時遵守の実行計画を作成するエージェント`

### ステップ 2: 指示 (Instructions) の登録
1. 作成したエージェントの **「概要 (Overview)」** タブを開きます。
2. **「指示 (Instructions)」** の入力エリアに、[`copilot_agent_instruction.md`](./copilot_agent_instruction.md) 内の Markdown テキストをすべてコピー＆ペーストします。
3. 画面右上の **「保存 (Save)」** をクリックします。

### ステップ 3: アクション（コネクタ）の追加
エージェントがユーザーのカレンダーとタスクを読み書きできるように、Microsoft 標準コネクタを追加します。

1. **「アクション (Actions)」** タブを選択し、**「+ アクションを追加 (Add an action)」** をクリックします。
2. 検索バーに `Office 365 Outlook` と入力し、以下のコネクタアクションを追加します：
   - **「カレンダーの予定の取得 (V4)」 (Get calendar view of events)**
   - **「予定の作成 (V4)」 (Create event)**
3. 再度 **「+ アクションを追加」** をクリックし、`Microsoft To Do` と検索して追加します：
   - **「タスクの取得」 (Get to-do tasks)**
   - **「タスクの更新」 (Update to-do task)**
4. 各アクションの接続設定で、ユーザー自身の M365 アカウント（委任された認証）が使用されるよう設定します。

---

## 3. 動作テスト

1. Copilot Studio 画面右側の **「エージェントのテスト (Test copilot)」** ペインを開きます。
2. チャット欄に以下のように入力します：
   ```text
   来週のスケジュールとタスク整理をお願いします。
   ```
3. エージェントが以下の通り応答することを確認します：
   - カレンダーの既存予定とTo Doタスクを一覧表示する
   - 午前中（08:45-12:30）に高集中タスクおよび仕上げ作業が配置されているか
   - 30分単位でタスクが分解されているか
   - 定時枠（17:30）に収まらない場合にWANTタスクの延期提案が出るか
   - スケジュール承認後にカレンダーへ登録されるか

---

## 4. Microsoft Teams および Outlook への公開 (Publish)

1. 画面右上の **「公開 (Publish)」** ボタンをクリックします。
2. **「チャネル (Channels)」** タブを開きます。
3. **Microsoft Teams**:
   - 「Teams を有効にする」をクリックし、社内共有用のリンクを取得、またはアプリカタログに登録します。
4. **Microsoft 365 Copilot (Outlook / M365 Chat)**:
   - 「Microsoft 365 Copilot に拡張」トグルをオンにします。
   - これにより、ユーザーは Outlook のサイドバーや Teams の Copilot チャットから直接 `@週次タスク・スケジュール最適化エージェント` と呼び出せるようになります。

---

## 5. （オプション）毎週金曜日の自動リマインド設定

毎週金曜日の 16:30 に自動でエージェントから通知を送るよう、**Power Automate** で簡単な定期トリガーフローを作成できます。

1. [Power Automate](https://make.powerautomate.com/) を開きます。
2. **「+ 作成」 > 「スケジュール済みクラウド フロー」** を選択。
   - フロー名: `金曜夕方タスク整理リマインド`
   - 繰り返し間隔: `毎週` / `金曜日` / 開始時刻: `16:30`
3. アクションに **「Microsoft Teams: チャットまたはチャネルでメッセージを投稿する」** を追加。
   - 投稿者: `Flow bot`
   - 投稿先: `Chat with Flow bot`
   - メッセージ:
     ```text
     お疲れ様です！今週も退勤時間が近づいてきました。
     翌週月曜日からスムーズに業務を開始できるよう、来週のタスク・スケジュール整理を実施しましょう。
     
     👉 「@週次タスク・スケジュール最適化エージェント 来週の予定を整理して」と送信してください。
     ```
4. 保存して有効化します。
