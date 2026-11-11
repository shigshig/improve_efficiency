#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
半期目標シート（Markdown）の品質検証スクリプト
- 3つの観点（売上貢献、人材育成、事業貢献）の存在確認
- 定量基準（数値・単位）の含有チェック
- 期限設定のチェック
- プレースホルダーの残存チェック
"""

import sys
import os
import re
import argparse
from typing import List, Dict, Tuple

REQUIRED_SECTIONS = [
    ("売上貢献", r"売上貢献"),
    ("人材育成", r"人材育成"),
    ("事業貢献", r"事業貢献"),
]

NUMBER_PATTERN = re.compile(r"\d+([,\.]\d+)?\s*(%|％|万|円|件|回|名|人|時間|h|pt|ポイント|日|社|本)")
DATE_PATTERN = re.compile(r"(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}月末|\d{4}年\d{1,2}月|Q[1-4]|第[1-4]四半期)")
PLACEHOLDER_PATTERN = re.compile(r"(\[[^\]]+\]|〇〇|XX|202X)")


def validate_file(file_path: str) -> Tuple[bool, List[str], List[str]]:
    """目標シートファイルを検証し、(is_valid, errors, warnings) を返す"""
    if not os.path.exists(file_path):
        return False, [f"ファイルが見つかりません: {file_path}"], []

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    errors: List[str] = []
    warnings: List[str] = []

    # 1. 必須セクションの存在確認
    for section_name, pattern in REQUIRED_SECTIONS:
        if not re.search(pattern, content):
            errors.append(f"【必須セクション欠落】「{section_name}」に関する記述が見つかりません。")

    # 2. セクションごとに分割して個別チェック
    sections = split_sections(content)

    for section_name, _ in REQUIRED_SECTIONS:
        sec_text = sections.get(section_name, "")
        if not sec_text:
            continue

        # 定量基準（数値）チェック
        if not NUMBER_PATTERN.search(sec_text):
            errors.append(f"【定量基準不足】「{section_name}」に具体的な数値・単位（例: 〇%、〇万円、〇件、〇名、〇時間）が見当たりません。")

        # 期限チェック
        if not DATE_PATTERN.search(sec_text):
            warnings.append(f"【期限不明確】「{section_name}」に具体的な達成期限（例: YYYY/MM/DD、〇月末）が見当たりません。")

    # 3. プレースホルダーの残存チェック
    placeholders = PLACEHOLDER_PATTERN.findall(content)
    if placeholders:
        sample_ph = ", ".join(list(set(placeholders))[:5])
        warnings.append(f"【未入力の可能性】テンプレートの仮テキストや未記入記号が残っています: {sample_ph}")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


def split_sections(content: str) -> Dict[str, str]:
    """コンテンツを3つのセクションに簡易分割する"""
    result = {}
    lines = content.splitlines()
    current_section = None
    buffer: List[str] = []

    for line in lines:
        matched = False
        for sec_name, pat in REQUIRED_SECTIONS:
            if re.search(r"###.*" + pat, line):
                if current_section and buffer:
                    result[current_section] = "\n".join(buffer)
                current_section = sec_name
                buffer = [line]
                matched = True
                break
        if not matched and current_section:
            buffer.append(line)

    if current_section and buffer:
        result[current_section] = "\n".join(buffer)

    return result


def main():
    parser = argparse.ArgumentParser(description="半期目標管理シートの品質検証ツール")
    parser.add_argument("file_path", help="検証対象のMarkdownファイルパス")
    args = parser.parse_args()

    print(f"=== 目標シート検証: {args.file_path} ===")
    is_valid, errors, warnings = validate_file(args.file_path)

    if errors:
        print("\n[!] エラー (修正必須):")
        for err in errors:
            print(f"  - {err}")

    if warnings:
        print("\n[*] 警告 (推奨修正):")
        for warn in warnings:
            print(f"  - {warn}")

    if is_valid and not warnings:
        print("\n[OK] すべての基準（3観点網羅・定量基準・期限設定）をクリアしています！")
        sys.exit(0)
    elif is_valid:
        print("\n[PASS] 必須項目は網羅されていますが、上記の警告項目を確認してください。")
        sys.exit(0)
    else:
        print("\n[FAIL] 必須要件を満たしていません。修正が必要です。")
        sys.exit(1)


if __name__ == "__main__":
    main()
