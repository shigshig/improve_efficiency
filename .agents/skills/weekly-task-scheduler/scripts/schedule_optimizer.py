#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
schedule_optimizer.py
翌週のスケジュールおよびタスク整理最適化エンジン

【ルール】
1. 午前中（08:45-12:30）は集中タイム。高集中タスクを配置。
2. 大きな作業は30分単位に分解し、最後の「仕上げ作業」は先行工程の後に午前集中枠に優先配置。
3. 定時退勤（17:30）を最優先。定時枠超過時はMUST以外の期限延期（リスケ）を提案。
4. MUSTのみで定時枠を超過する場合のみ、最小限の残業時間を30分単位で予測。
5. 空き枠がある場合は、期限に余裕のあるタスクを前倒し配置。
"""

import sys
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

# スロット定義
MORNING_SLOTS = [
    ("08:45", "09:15"),
    ("09:15", "09:45"),
    ("09:45", "10:15"),
    ("10:15", "10:45"),
    ("10:45", "11:15"),
    ("11:15", "11:45"),
    ("11:45", "12:30"),  # 45分スロット（まとめ・バッファ）
]

AFTERNOON_SLOTS = [
    ("13:30", "14:00"),
    ("14:00", "14:30"),
    ("14:30", "15:00"),
    ("15:00", "15:30"),
    ("15:30", "16:00"),
    ("16:00", "16:30"),
    ("16:30", "17:00"),
    ("17:00", "17:30"),
]

OVERTIME_SLOTS = [
    ("17:30", "18:00"),
    ("18:00", "18:30"),
    ("18:30", "19:00"),
    ("19:00", "19:30"),
]

DAYS = ["月", "火", "水", "木", "金"]


class TaskItem:
    def __init__(
        self,
        name: str,
        hours: float,
        priority: str = "MUST",  # MUST, WANT, BACKLOG
        due_day: Optional[str] = None,  # 月, 火, 水, 木, 金, or None
        is_focus: bool = True,  # True: 午前希望, False: 午後希望
        decompose: bool = True,
        notes: str = "",
        subtasks: Optional[List[Dict[str, Any]]] = None,  # AIによる事前分解サブタスク
    ):
        self.name = name
        self.hours = hours
        self.priority = priority.upper()
        self.due_day = due_day
        self.is_focus = is_focus
        self.decompose = decompose
        self.notes = notes
        self.custom_subtasks = subtasks or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "hours": self.hours,
            "priority": self.priority,
            "due_day": self.due_day,
            "is_focus": self.is_focus,
            "decompose": self.decompose,
            "notes": self.notes,
            "subtasks": self.custom_subtasks,
        }


class SubTask:
    def __init__(
        self,
        parent_name: str,
        name: str,
        priority: str,
        due_day: Optional[str],
        is_focus: bool,
        step_index: int,
        total_steps: int,
        is_finishing: bool = False,
    ):
        self.parent_name = parent_name
        self.name = name
        self.priority = priority
        self.due_day = due_day
        self.is_focus = is_focus
        self.step_index = step_index
        self.total_steps = total_steps
        self.is_finishing = is_finishing  # 仕上げ作業フラグ


class DaySchedule:
    def __init__(self, day_name: str, date_str: str = "", day_index: int = 0):
        self.day_name = day_name
        self.date_str = date_str
        self.day_index = day_index
        self.slots: Dict[str, Dict[str, Any]] = {}

        # スロット初期化
        slot_order = 0
        for start, end in MORNING_SLOTS:
            key = f"{start}-{end}"
            self.slots[key] = {
                "period": "MORNING",
                "start": start,
                "end": end,
                "category": "FREE",
                "content": "",
                "is_finishing": False,
                "global_order": day_index * 100 + slot_order,
            }
            slot_order += 1

        for start, end in AFTERNOON_SLOTS:
            key = f"{start}-{end}"
            self.slots[key] = {
                "period": "AFTERNOON",
                "start": start,
                "end": end,
                "category": "FREE",
                "content": "",
                "is_finishing": False,
                "global_order": day_index * 100 + slot_order,
            }
            slot_order += 1

        self.overtime_slots: List[Dict[str, Any]] = []

    def get_free_morning_keys(self, min_global_order: int = -1) -> List[str]:
        return [
            k
            for k, v in self.slots.items()
            if v["period"] == "MORNING"
            and v["category"] == "FREE"
            and v["global_order"] > min_global_order
        ]

    def get_free_afternoon_keys(self, min_global_order: int = -1) -> List[str]:
        return [
            k
            for k, v in self.slots.items()
            if v["period"] == "AFTERNOON"
            and v["category"] == "FREE"
            and v["global_order"] > min_global_order
        ]

    def get_all_free_keys(self, min_global_order: int = -1) -> List[str]:
        return [
            k
            for k, v in self.slots.items()
            if v["category"] == "FREE" and v["global_order"] > min_global_order
        ]

    def assign_meeting(self, start: str, end: str, title: str):
        for k, v in self.slots.items():
            if not (end <= v["start"] or start >= v["end"]):
                v["category"] = "MEETING"
                v["content"] = f"【会議】{title}"

    def assign_task(self, slot_key: str, subtask: SubTask) -> int:
        self.slots[slot_key]["category"] = (
            "FINISHING_TASK" if subtask.is_finishing else "TASK"
        )
        fin_tag = "【仕上げ作業・集中】" if (subtask.is_finishing and not subtask.name.startswith("【仕上げ")) else ""
        self.slots[slot_key]["content"] = f"{fin_tag}{subtask.name}"
        self.slots[slot_key]["is_finishing"] = subtask.is_finishing
        return self.slots[slot_key]["global_order"]

    def add_overtime(self, subtask: SubTask) -> Tuple[str, int]:
        idx = len(self.overtime_slots)
        if idx < len(OVERTIME_SLOTS):
            start, end = OVERTIME_SLOTS[idx]
        else:
            start = f"19:{30 + (idx - len(OVERTIME_SLOTS))*30}"
            end = f"20:{00 + (idx - len(OVERTIME_SLOTS))*30}"
        global_order = self.day_index * 100 + 50 + idx
        slot_info = {
            "period": "OVERTIME",
            "start": start,
            "end": end,
            "category": "OVERTIME_TASK",
            "content": f"【残業】{subtask.name}",
            "global_order": global_order,
        }
        self.overtime_slots.append(slot_info)
        return f"{start}-{end}", global_order


class WeeklyOptimizer:
    def __init__(self, start_date: str = "2026-11-16"):
        self.start_date = start_date
        self.schedules: Dict[str, DaySchedule] = {}
        dt = datetime.strptime(start_date, "%Y-%m-%d")
        for i, d in enumerate(DAYS):
            cur_dt = dt + timedelta(days=i)
            self.schedules[d] = DaySchedule(d, cur_dt.strftime("%m/%d"), day_index=i)

        self.reschedule_proposals: List[str] = []
        self.early_tasks: List[str] = []
        self.overtime_summary: Dict[str, float] = {d: 0.0 for d in DAYS}

    def add_meeting(self, day: str, start: str, end: str, title: str):
        if day in self.schedules:
            self.schedules[day].assign_meeting(start, end, title)

    def decompose_task(self, task: TaskItem) -> List[SubTask]:
        """タスクを30分スロットのサブタスクに分解する。
        AIが生成したカスタムサブタスク (custom_subtasks) が存在する場合はそれを優先採用する。
        """
        # 1. AIによる事前分解サブタスクが指定されている場合
        if task.custom_subtasks:
            total_steps = len(task.custom_subtasks)
            subtasks = []
            for i, st in enumerate(task.custom_subtasks):
                is_fin = st.get("is_finishing", i == (total_steps - 1))
                sub_name = st.get("name", f"{task.name} Part {i+1}")
                sub_focus = st.get("is_focus", True if is_fin else task.is_focus)
                sub_due = st.get("due_day", task.due_day)
                subtasks.append(
                    SubTask(
                        parent_name=task.name,
                        name=sub_name,
                        priority=task.priority,
                        due_day=sub_due,
                        is_focus=sub_focus,
                        step_index=i,
                        total_steps=total_steps,
                        is_finishing=is_fin,
                    )
                )
            return subtasks

        # 2. 未指定時のフォールバック分解 (時間数から自動計算)
        slots_count = max(1, int(round(task.hours * 2)))
        subtasks = []

        if not task.decompose or slots_count == 1:
            subtasks.append(
                SubTask(
                    parent_name=task.name,
                    name=task.name,
                    priority=task.priority,
                    due_day=task.due_day,
                    is_focus=task.is_focus,
                    step_index=0,
                    total_steps=1,
                    is_finishing=task.is_focus,
                )
            )
            return subtasks

        for i in range(slots_count):
            is_last = i == (slots_count - 1)
            step_num = i + 1
            if is_last:
                sub_name = f"{task.name} [最終仕上げ・レビュー準備]"
                subtasks.append(
                    SubTask(
                        parent_name=task.name,
                        name=sub_name,
                        priority=task.priority,
                        due_day=task.due_day,
                        is_focus=True,  # 仕上げは必ず午前集中
                        step_index=i,
                        total_steps=slots_count,
                        is_finishing=True,
                    )
                )
            else:
                if step_num == 1:
                    role_desc = "構成案・要件整理"
                elif step_num == 2:
                    role_desc = "ドラフト作成・情報収集"
                else:
                    role_desc = f"実務作成・肉付け Part {step_num-1}"

                sub_name = f"{task.name} [{role_desc}]"
                subtasks.append(
                    SubTask(
                        parent_name=task.name,
                        name=sub_name,
                        priority=task.priority,
                        due_day=task.due_day,
                        is_focus=task.is_focus,
                        step_index=i,
                        total_steps=slots_count,
                        is_finishing=False,
                    )
                )

        return subtasks

    def optimize(self, tasks: List[TaskItem]) -> Dict[str, Any]:
        """スケジュール最適化メインルーチン"""

        # 1. タスクのグルーピングと順序付け
        day_order = {d: i for i, d in enumerate(DAYS)}
        day_order[None] = 99

        # MUSTタスクとWANTタスクとBACKLOGタスクに分類
        must_tasks = [t for t in tasks if t.priority == "MUST"]
        want_tasks = [t for t in tasks if t.priority == "WANT"]
        backlog_tasks = [t for t in tasks if t.priority == "BACKLOG"]

        # MUSTタスクを期限が早い順にソート
        must_tasks.sort(key=lambda t: day_order.get(t.due_day, 99))
        want_tasks.sort(key=lambda t: day_order.get(t.due_day, 99))

        # 2. タスクを1つずつ順番に配置（サブタスク間の先行・後続依存性を維持）
        for task in must_tasks + want_tasks:
            subtasks = self.decompose_task(task)
            last_global_order = -1
            task_failed = False

            for sub in subtasks:
                target_days = DAYS
                if sub.due_day and sub.due_day in day_order:
                    limit_idx = day_order[sub.due_day]
                    target_days = DAYS[: limit_idx + 1]

                assigned = False

                # (A) 仕上げ作業の場合: 先行作業の後 かつ 午前集中枠 (08:45-12:30) に配置
                if sub.is_finishing:
                    for d in target_days:
                        free_m = self.schedules[d].get_free_morning_keys(
                            min_global_order=last_global_order
                        )
                        if free_m:
                            slot_key = free_m[0]
                            last_global_order = self.schedules[d].assign_task(
                                slot_key, sub
                            )
                            assigned = True
                            break

                # (B) 先行作業 または 通常の集中作業
                elif sub.is_focus:
                    # まず午前枠を探索
                    for d in target_days:
                        free_m = self.schedules[d].get_free_morning_keys(
                            min_global_order=last_global_order
                        )
                        if free_m:
                            slot_key = free_m[0]
                            last_global_order = self.schedules[d].assign_task(
                                slot_key, sub
                            )
                            assigned = True
                            break
                    # 午前が埋まっていれば午後枠も許可
                    if not assigned:
                        for d in target_days:
                            free_a = self.schedules[d].get_free_afternoon_keys(
                                min_global_order=last_global_order
                            )
                            if free_a:
                                slot_key = free_a[0]
                                last_global_order = self.schedules[d].assign_task(
                                    slot_key, sub
                                )
                                assigned = True
                                break

                # (C) 午後希望の通常作業
                else:
                    for d in target_days:
                        free_a = self.schedules[d].get_free_afternoon_keys(
                            min_global_order=last_global_order
                        )
                        if free_a:
                            slot_key = free_a[0]
                            last_global_order = self.schedules[d].assign_task(
                                slot_key, sub
                            )
                            assigned = True
                            break
                    # 午後が埋まっていれば午前枠も許可
                    if not assigned:
                        for d in target_days:
                            free_m = self.schedules[d].get_free_morning_keys(
                                min_global_order=last_global_order
                            )
                            if free_m:
                                slot_key = free_m[0]
                                last_global_order = self.schedules[d].assign_task(
                                    slot_key, sub
                                )
                                assigned = True
                                break

                # (D) 定時枠に収まらなかった場合
                if not assigned:
                    task_failed = True
                    if task.priority == "WANT":
                        prop = f"【期限延期提案】'{task.name}' (WANT) は来週の定時枠に収まらないため、翌々週以降への延期を推奨します。"
                        if prop not in self.reschedule_proposals:
                            self.reschedule_proposals.append(prop)
                        break  # 残りのサブタスクもスキップ
                    else:
                        # MUSTタスクは最終手段として残業枠を算出
                        assign_day = sub.due_day if sub.due_day in DAYS else DAYS[-1]
                        slot_range, last_global_order = self.schedules[
                            assign_day
                        ].add_overtime(sub)
                        self.overtime_summary[assign_day] += 0.5

        # 3. 前倒し対応: 定時枠に空きスロットがある場合、BACKLOGタスクを配置
        for b_task in backlog_tasks:
            subtasks = self.decompose_task(b_task)
            for sub in subtasks:
                assigned = False
                for d in DAYS:
                    free_slots = self.schedules[d].get_all_free_keys()
                    if free_slots:
                        target_slot = free_slots[0]
                        self.schedules[d].assign_task(target_slot, sub)
                        ear_msg = f"【前倒し配置】{d}曜 {target_slot}: '{sub.parent_name}' (余裕タスクを前倒し実行)"
                        self.early_tasks.append(ear_msg)
                        assigned = True
                        break
                if not assigned:
                    break

        return self.generate_report()

    def generate_report(self) -> Dict[str, Any]:
        """Markdown形式のサマリーとタイムテーブルを生成"""
        total_slots = 0
        meeting_slots = 0
        task_slots = 0
        finishing_slots = 0
        free_slots = 0
        overtime_slots = sum(len(s.overtime_slots) for s in self.schedules.values())

        for s in self.schedules.values():
            for slot in s.slots.values():
                total_slots += 1
                cat = slot["category"]
                if cat == "MEETING":
                    meeting_slots += 1
                elif cat == "FINISHING_TASK":
                    finishing_slots += 1
                    task_slots += 1
                elif cat == "TASK":
                    task_slots += 1
                elif cat == "FREE":
                    free_slots += 1

        total_task_hours = (task_slots + overtime_slots) * 0.5
        available_hours = (total_slots - meeting_slots) * 0.5
        meeting_hours = meeting_slots * 0.5
        buffer_hours = free_slots * 0.5
        total_overtime_hours = overtime_slots * 0.5

        if total_overtime_hours == 0:
            ot_summary = "なし（定時退勤可能です）"
        else:
            details = [
                f"{d}曜: {hrs}時間"
                for d, hrs in self.overtime_summary.items()
                if hrs > 0
            ]
            ot_summary = f"週計 {total_overtime_hours} 時間予測 ({', '.join(details)}) ※定時超過のため要注意"

        resched_text = (
            "\n".join(f"- {p}" for p in self.reschedule_proposals)
            if self.reschedule_proposals
            else "なし（すべての予定・タスクが定時枠内に順調に収まりました）"
        )

        early_text = (
            "\n".join(f"- {e}" for e in self.early_tasks)
            if self.early_tasks
            else "なし（今週の定時枠はフル稼働です）"
        )

        table_rows = []
        header = (
            "| 時間帯 | "
            + " | ".join(f"{d} ({self.schedules[d].date_str})" for d in DAYS)
            + " |"
        )
        separator = "| :--- | " + " | ".join([":---"] * len(DAYS)) + " |"
        table_rows.append(header)
        table_rows.append(separator)

        for s, e in MORNING_SLOTS:
            key = f"{s}-{e}"
            row = [f"**{key}**"]
            for d in DAYS:
                val = self.schedules[d].slots[key]["content"] or "*(空き/集中枠)*"
                row.append(val)
            table_rows.append("| " + " | ".join(row) + " |")

        table_rows.append(
            "| *12:30-13:30* | " + " | ".join(["*昼休憩*"] * len(DAYS)) + " |"
        )

        for s, e in AFTERNOON_SLOTS:
            key = f"{s}-{e}"
            row = [f"**{key}**"]
            for d in DAYS:
                val = self.schedules[d].slots[key]["content"] or "*(空き/通常枠)*"
                row.append(val)
            table_rows.append("| " + " | ".join(row) + " |")

        row_ot = ["**17:30以降 (残業)**"]
        for d in DAYS:
            ots = self.schedules[d].overtime_slots
            if ots:
                ot_str = "<br>".join(
                    f"{o['start']}-{o['end']}: {o['content']}" for o in ots
                )
                row_ot.append(ot_str)
            else:
                row_ot.append("なし（定時退社）")
        table_rows.append("| " + " | ".join(row_ot) + " |")

        timetable_md = "\n".join(table_rows)

        action_list_lines = []
        for d in DAYS:
            action_list_lines.append(f"### {d}曜日 ({self.schedules[d].date_str})")
            m_tasks = [
                f"  - {slot['start']}-{slot['end']} {slot['content']}"
                for slot in self.schedules[d].slots.values()
                if slot["period"] == "MORNING" and slot["content"]
            ]
            if m_tasks:
                action_list_lines.append("- **【午前集中タイム (08:45-12:30)】**")
                action_list_lines.extend(m_tasks)

            a_tasks = [
                f"  - {slot['start']}-{slot['end']} {slot['content']}"
                for slot in self.schedules[d].slots.values()
                if slot["period"] == "AFTERNOON" and slot["content"]
            ]
            if a_tasks:
                action_list_lines.append("- **【午後通常タイム (13:30-17:30)】**")
                action_list_lines.extend(a_tasks)

            if self.schedules[d].overtime_slots:
                action_list_lines.append("- **【残業タイム (17:30〜)】**")
                for o in self.schedules[d].overtime_slots:
                    action_list_lines.append(
                        f"  - {o['start']}-{o['end']} {o['content']}"
                    )
            action_list_lines.append("")

        action_list_md = "\n".join(action_list_lines)

        full_md = f"""# 翌週実行計画サマリー ({self.schedules['月'].date_str} 〜 {self.schedules['金'].date_str})

## 1. 稼働・工数サマリー
- **タスク総工数**: {total_task_hours} 時間
- **利用可能稼働枠**: {available_hours} 時間 (固定会議: {meeting_hours} 時間)
- **残業予測**: {ot_summary}
- **空きバッファ時間**: {buffer_hours} 時間 (突発タスク対応枠)

---

## 2. 期限調整・リスケジュール提案
{resched_text}

---

## 3. 前倒し対応タスク
{early_text}

---

## 4. 週間タイムテーブル (08:45 〜 17:30)

{timetable_md}

---

## 5. 日別アクションリスト

{action_list_md}
"""
        return {
            "markdown": full_md,
            "total_task_hours": total_task_hours,
            "meeting_hours": meeting_hours,
            "overtime_hours": total_overtime_hours,
            "buffer_hours": buffer_hours,
            "reschedule_proposals": self.reschedule_proposals,
            "early_tasks": self.early_tasks,
        }


def run_test():
    """テストケースの実行と検証"""
    print("=" * 60)
    print("schedule_optimizer.py テストケース実行 (通常ケース)")
    print("=" * 60)

    opt = WeeklyOptimizer(start_date="2026-11-16")

    # 1. 固定会議の登録
    opt.add_meeting("月", "09:00", "09:45", "週次全体朝会")
    opt.add_meeting("水", "14:00", "15:00", "プロジェクト進捗定例")
    opt.add_meeting("金", "16:30", "17:30", "振り返り & 次週計画")

    # 2. タスクの登録
    sample_tasks = [
        # AIが文脈を考慮して具体的に分解したタスク (2.0h = 4サブタスク)
        TaskItem(
            name="四半期営業報告書の作成",
            hours=2.0,
            priority="MUST",
            due_day="火",
            subtasks=[
                {"name": "四半期営業報告書 [営業数値の抽出と集計]", "is_focus": True, "is_finishing": False},
                {"name": "四半期営業報告書 [未達要因と競合動向の分析]", "is_focus": True, "is_finishing": False},
                {"name": "四半期営業報告書 [来期施策スライドのドラフト化]", "is_focus": False, "is_finishing": False},
                {"name": "四半期営業報告書 [役員向けサマリー推敲・最終チェック]", "is_focus": True, "is_finishing": True},
            ],
        ),
        # 集中作業: 1.5h (フォールバック分解)
        TaskItem(
            name="新規事業提案書のドラフト",
            hours=1.5,
            priority="MUST",
            due_day="水",
            is_focus=True,
            decompose=True,
        ),
        # 通常作業: 1.0h (月曜午後に配置)
        TaskItem(
            name="クライアント向けメール送付・連絡",
            hours=1.0,
            priority="MUST",
            due_day="月",
            is_focus=False,
            decompose=False,
        ),
        # WANTタスク: 3.0h
        TaskItem(
            name="社内ナレッジBaseドキュメント整備",
            hours=3.0,
            priority="WANT",
            due_day="木",
            is_focus=False,
            decompose=True,
        ),
        # 余裕タスク: 期限なし -> 空き枠に前倒し配置
        TaskItem(
            name="次世代ツール調査・検証",
            hours=1.0,
            priority="BACKLOG",
            due_day=None,
            is_focus=False,
            decompose=True,
        ),
    ]

    result = opt.optimize(sample_tasks)
    print(result["markdown"])
    print("\n[テスト結果判定]")
    print(f"- タスク総工数: {result['total_task_hours']}h")
    print(f"- 会議工数: {result['meeting_hours']}h")
    print(f"- 残業工数: {result['overtime_hours']}h")
    print(f"- 空きバッファ: {result['buffer_hours']}h")
    print(f"- リスケ提案件数: {len(result['reschedule_proposals'])}件")
    print(f"- 前倒し配置件数: {len(result['early_tasks'])}件")
    print("=" * 60)

    # 3. 過積載・残業予測テスト (月曜にMUSTタスク集中)
    print("\n" + "=" * 60)
    print("schedule_optimizer.py テストケース実行 (過積載・残業予測ケース)")
    print("=" * 60)
    opt_heavy = WeeklyOptimizer(start_date="2026-11-16")
    opt_heavy.add_meeting("月", "09:00", "12:00", "幹部報告会")
    heavy_tasks = [
        # 月曜午後だけでは収まらないMUSTタスク群 (計6.0h、午後枠は4.0h)
        TaskItem(name="緊急障害対応報告", hours=3.0, priority="MUST", due_day="月", is_focus=True),
        TaskItem(name="重要顧客トラブルフォロー", hours=2.5, priority="MUST", due_day="月", is_focus=False),
        TaskItem(name="定例マニュアル更新", hours=2.0, priority="WANT", due_day="月", is_focus=False),
    ]
    res_heavy = opt_heavy.optimize(heavy_tasks)
    print(f"- 重負荷テスト リスケ提案: {res_heavy['reschedule_proposals']}")
    print(f"- 重負荷テスト 残業工数予測: {res_heavy['overtime_hours']}h")
    assert len(res_heavy['reschedule_proposals']) > 0, "WANTタスクのリスケ提案が生成されること"
    assert res_heavy['overtime_hours'] > 0, "定時枠超過により残業時間が予測されること"
    print("過積載テスト完了: WANTの延期提案および残業予測が正常に動作しました。")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Weekly Schedule Optimizer")
    parser.add_argument("--test", action="store_true", help="Run self-test with sample data")
    parser.add_argument("--input", type=str, help="JSON input file with tasks and meetings")
    parser.add_argument("--output", type=str, help="Markdown output file path")
    parser.add_argument("--start-date", type=str, default="2026-11-16", help="Start date (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.test:
        run_test()
        return

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)

        opt = WeeklyOptimizer(start_date=data.get("start_date", args.start_date))

        for m in data.get("meetings", []):
            opt.add_meeting(m["day"], m["start"], m["end"], m["title"])

        tasks = [
            TaskItem(
                name=t["name"],
                hours=t["hours"],
                priority=t.get("priority", "MUST"),
                due_day=t.get("due_day"),
                is_focus=t.get("is_focus", True),
                decompose=t.get("decompose", True),
                notes=t.get("notes", ""),
                subtasks=t.get("subtasks"),
            )
            for t in data.get("tasks", [])
        ]

        result = opt.optimize(tasks)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(result["markdown"])
            print(f"Report written to {args.output}")
        else:
            print(result["markdown"])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
