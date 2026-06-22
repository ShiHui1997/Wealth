"""
解析 GitHub Issue 中的开奖数据并写入数据库
从 GitHub Actions 调用，通过环境变量接收 Issue 数据
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime


def main():
    title = os.environ.get("ISSUE_TITLE", "")
    body = os.environ.get("ISSUE_BODY", "")
    issue_number = os.environ.get("ISSUE_NUMBER", "0")

    print(f"[提交处理] Issue #{issue_number}: {title}")
    print(f"[提交处理] Body 前200字: {body[:200]}")

    # 手动触发时（workflow_dispatch），跳过解析
    if not title and not body:
        print("[提交处理] 手动触发模式，跳过 Issue 解析")
        # 写入空的 submission_result.json 让后续步骤知道没有数据
        with open("submission_result.json", "w") as f:
            json.dump({"skipped": True}, f)
        return

    # 解析期号
    issue_match = re.search(r"开奖提交\s*(\d+)", title)
    if not issue_match:
        issue_match = re.search(r"期号[：:]\s*\*?(\d+)", body)
    if not issue_match:
        print("[提交处理] 错误：无法解析期号")
        sys.exit(1)

    issue_no = issue_match.group(1).strip()
    print(f"[提交处理] 期号: {issue_no}")

    # 解析前区号码（5个）
    front_match = re.search(r"前区\s*[|]\s*([\d\s]+)", body)
    if front_match:
        front_nums = [int(x) for x in front_match.group(1).split() if x.strip()]
    else:
        print("[提交处理] 错误：无法解析前区号码")
        sys.exit(1)

    # 解析后区号码（2个）
    back_match = re.search(r"后区\s*[|]\s*([\d\s]+)", body)
    if back_match:
        back_nums = [int(x) for x in back_match.group(1).split() if x.strip()]
    else:
        print("[提交处理] 错误：无法解析后区号码")
        sys.exit(1)

    print(f"[提交处理] 前区: {front_nums}")
    print(f"[提交处理] 后区: {back_nums}")

    if len(front_nums) != 5 or len(back_nums) != 2:
        print(
            f"[提交处理] 错误：号码数量不对"
            f"（前区需要5个实际{len(front_nums)}个，后区需要2个实际{len(back_nums)}个）"
        )
        sys.exit(1)

    # 格式化并写入数据库
    front_str = " ".join(f"{n:02d}" for n in sorted(front_nums))
    back_str = " ".join(f"{n:02d}" for n in sorted(back_nums))

    draw_date = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect("data/daletou.db")
    try:
        conn.execute(
            "INSERT OR IGNORE INTO draws "
            "(issue, draw_date, front_numbers, back_numbers, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (issue_no, draw_date, f"[{front_str}]", f"[{back_str}]",
             datetime.now().isoformat()),
        )
        conn.commit()
        print(f"[提交处理] ✅ 数据已入库: {issue_no} | {front_str} + {back_str}")
    finally:
        conn.close()

    # 保存解析结果供后续步骤使用
    with open("submission_result.json", "w") as f:
        json.dump({"issue": issue_no, "front": front_str, "back": back_str}, f)


if __name__ == "__main__":
    main()
