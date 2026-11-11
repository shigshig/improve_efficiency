#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
m365_client.py
Microsoft 365 (Outlook Calendar & Microsoft To Do) 連携クライアント

【機能】
1. Device Code Flow (OAuth2) によるトークン取得と安全なローカルキャッシュ
2. Outlook カレンダーの既存予定（会議等）の取得
3. Microsoft To Do の未完了タスク一覧の取得
4. 確定スケジュールの Outlook カレンダーへの作業ブロック一括登録
5. Microsoft To Do タスクの期日更新
6. （フォールバック）カレンダー用 .ics ファイルの一括エクスポート
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

# Microsoft Graph API 設定
DEFAULT_CLIENT_ID = os.environ.get("M365_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
DEFAULT_TENANT_ID = os.environ.get("M365_TENANT_ID", "common")
SCOPES = ["Calendars.ReadWrite", "Tasks.ReadWrite", "User.Read", "offline_access"]
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE_PATH = os.path.expanduser("~/.m365_token_cache.json")


class M365Client:
    def __init__(self, client_id: str = DEFAULT_CLIENT_ID, tenant_id: str = DEFAULT_TENANT_ID):
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry: float = 0.0
        self.load_token_cache()

    def load_token_cache(self):
        if os.path.exists(TOKEN_CACHE_PATH):
            try:
                with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
                    self.token_expiry = data.get("expires_at", 0.0)
            except Exception as e:
                print(f"[Warn] トークンキャッシュ読み込み失敗: {e}", file=sys.stderr)

    def save_token_cache(self, token_data: Dict[str, Any]):
        expires_in = token_data.get("expires_in", 3600)
        cache_data = {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token") or self.refresh_token,
            "expires_at": time.time() + expires_in - 60,
        }
        self.access_token = cache_data["access_token"]
        self.refresh_token = cache_data["refresh_token"]
        self.token_expiry = cache_data["expires_at"]
        try:
            with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
            print(f"[Info] トークンキャッシュを保存しました: {TOKEN_CACHE_PATH}")
        except Exception as e:
            print(f"[Error] トークンキャッシュ保存失敗: {e}", file=sys.stderr)

    def start_device_code_flow(self):
        """Device Code Flowを開始して認証URLとコードを表示"""
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/devicecode"
        body = urllib.parse.urlencode({
            "client_id": self.client_id,
            "scope": " ".join(SCOPES),
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[Error] デバイスコード取得エラー: {e}", file=sys.stderr)
            print("※ Azure AD の Client ID が設定されているか確認してください。")
            return False

        user_code = data["user_code"]
        verification_uri = data["verification_uri"]
        device_code = data["device_code"]
        interval = data.get("interval", 5)
        expires_in = data.get("expires_in", 900)

        print("\n" + "=" * 60)
        print("【Microsoft 365 認証】")
        print(f"1. ブラウザで以下のURLを開いてください:\n   {verification_uri}")
        print(f"2. 次のコードを入力してサインインを承認してください:\n   >> {user_code} <<")
        print("=" * 60 + "\n")

        # ポーリング
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        poll_body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self.client_id,
            "device_code": device_code,
        }).encode("utf-8")

        end_time = time.time() + expires_in
        while time.time() < end_time:
            time.sleep(interval)
            poll_req = urllib.request.Request(token_url, data=poll_body, headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with urllib.request.urlopen(poll_req) as resp:
                    t_data = json.loads(resp.read().decode("utf-8"))
                    self.save_token_cache(t_data)
                    print("[Success] サインインに成功しました！")
                    return True
            except urllib.error.HTTPError as he:
                err_resp = json.loads(he.read().decode("utf-8"))
                error = err_resp.get("error")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    interval += 5
                    continue
                elif error in ["expired_token", "access_denied"]:
                    print(f"[Error] 認証失敗またはタイムアウト: {error}", file=sys.stderr)
                    return False
                else:
                    print(f"[Error] 認証例外: {err_resp}", file=sys.stderr)
                    return False

        print("[Error] 認証待機がタイムアウトしました。", file=sys.stderr)
        return False

    def refresh_access_token(self) -> bool:
        """リフレッシュトークンを使用してアクセストークンを再取得"""
        if not self.refresh_token:
            return False
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
            "scope": " ".join(SCOPES),
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.save_token_cache(data)
                return True
        except Exception as e:
            print(f"[Warn] トークン更新失敗: {e}", file=sys.stderr)
            return False

    def get_headers(self) -> Dict[str, str]:
        if time.time() >= self.token_expiry:
            if not self.refresh_access_token():
                raise RuntimeError("認証が必要です。--login を実行してください。")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def api_get(self, endpoint: str) -> Dict[str, Any]:
        headers = self.get_headers()
        url = f"{GRAPH_BASE_URL}{endpoint}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def api_post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        headers = self.get_headers()
        url = f"{GRAPH_BASE_URL}{endpoint}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def api_patch(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        headers = self.get_headers()
        url = f"{GRAPH_BASE_URL}{endpoint}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="PATCH")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # === カレンダー関連 ===
    def get_calendar_events(self, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
        """指定期間の予定を取得"""
        endpoint = f"/me/calendarView?startDateTime={start_iso}&endDateTime={end_iso}&$select=subject,start,end,isAllDay,showAs&$top=100"
        res = self.api_get(endpoint)
        events = []
        for item in res.get("value", []):
            events.append({
                "title": item["subject"],
                "start": item["start"]["dateTime"],
                "end": item["end"]["dateTime"],
                "is_all_day": item.get("isAllDay", False),
            })
        return events

    def create_calendar_event(self, subject: str, start_iso: str, end_iso: str, body: str = "") -> Dict[str, Any]:
        """作業ブロックイベントを作成"""
        event_payload = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body},
            "start": {"dateTime": start_iso, "timeZone": "Tokyo Standard Time"},
            "end": {"dateTime": end_iso, "timeZone": "Tokyo Standard Time"},
            "showAs": "busy",
            "categories": ["Focus Time" if "仕上げ" in subject or "集中" in subject else "Task Work"],
        }
        return self.api_post("/me/events", event_payload)

    # === Microsoft To Do 関連 ===
    def get_todo_tasks(self) -> List[Dict[str, Any]]:
        """To Doの未完了タスクを取得"""
        # まずタスクリスト一覧を取得
        lists_res = self.api_get("/me/todo/lists")
        all_tasks = []
        for t_list in lists_res.get("value", []):
            list_id = t_list["id"]
            list_name = t_list["displayName"]
            # 未完了タスクを取得
            tasks_res = self.api_get(f"/me/todo/lists/{list_id}/tasks?$filter=status ne 'completed'&$top=100")
            for task in tasks_res.get("value", []):
                due_obj = task.get("dueDateTime")
                due_date = due_obj.get("dateTime")[:10] if due_obj else None
                all_tasks.append({
                    "id": task["id"],
                    "list_id": list_id,
                    "list_name": list_name,
                    "title": task["title"],
                    "importance": task.get("importance", "normal"),  # high -> MUST
                    "due_date": due_date,
                    "body": task.get("body", {}).get("content", ""),
                })
        return all_tasks

    def update_task_due_date(self, list_id: str, task_id: str, due_date_str: str) -> Dict[str, Any]:
        """タスクの期日を更新 (YYYY-MM-DD)"""
        payload = {
            "dueDateTime": {
                "dateTime": f"{due_date_str}T00:00:00",
                "timeZone": "Tokyo Standard Time"
            }
        }
        return self.api_patch(f"/me/todo/lists/{list_id}/tasks/{task_id}", payload)


def export_to_ics(slots_data: List[Dict[str, Any]], output_path: str):
    """カレンダー登録用の標準 iCalendar (.ics) ファイルを生成"""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Antigravity//Weekly Task Scheduler//JA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for slot in slots_data:
        # slot: {"title": str, "date": "2026-11-16", "start": "08:45", "end": "09:15", "desc": str}
        date_str = slot["date"].replace("-", "")
        start_str = date_str + "T" + slot["start"].replace(":", "") + "00"
        end_str = date_str + "T" + slot["end"].replace(":", "") + "00"
        uid = f"{start_str}-{abs(hash(slot['title']))}@antigravity.local"

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART;TZID=Asia/Tokyo:{start_str}",
            f"DTEND;TZID=Asia/Tokyo:{end_str}",
            f"SUMMARY:{slot['title']}",
            f"DESCRIPTION:{slot.get('desc', '')}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")
    print(f"[Success] iCalendar ファイルを出力しました: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Microsoft 365 Integration Client")
    parser.add_argument("--login", action="store_true", help="Start Device Code Flow login")
    parser.add_argument("--get-events", action="store_true", help="Fetch calendar events")
    parser.add_argument("--get-tasks", action="store_true", help="Fetch Microsoft To Do tasks")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--export-ics", type=str, help="Export events to .ics file path")
    parser.add_argument("--input-json", type=str, help="JSON file with schedule events")

    args = parser.parse_args()
    client = M365Client()

    if args.login:
        client.start_device_code_flow()
        return

    if args.get_events:
        if not args.start_date or not args.end_date:
            print("[Error] --start-date と --end-date が必要です (例: 2026-11-16)", file=sys.stderr)
            sys.exit(1)
        start_iso = f"{args.start_date}T00:00:00Z"
        end_iso = f"{args.end_date}T23:59:59Z"
        try:
            events = client.get_calendar_events(start_iso, end_iso)
            print(json.dumps(events, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[Error] カレンダー予定取得エラー: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.get_tasks:
        try:
            tasks = client.get_todo_tasks()
            print(json.dumps(tasks, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[Error] To Doタスク取得エラー: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.export_ics and args.input_json:
        with open(args.input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        export_to_ics(data, args.export_ics)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
