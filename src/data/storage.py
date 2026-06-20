"""
大乐透数据存储模块
使用 SQLite 存储历史开奖数据
"""
import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple


class LotteryStorage:
    """大乐透数据存储"""

    def __init__(self, db_path: str = "data/daletou.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS draws (
                    issue TEXT PRIMARY KEY,          -- 期号 (如 2024001)
                    draw_date TEXT NOT NULL,         -- 开奖日期
                    front_numbers TEXT NOT NULL,     -- 前区号码 JSON [1,5,12,23,35]
                    back_numbers TEXT NOT NULL,      -- 后区号码 JSON [3,8]
                    created_at TEXT NOT NULL         -- 记录创建时间
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_draw_date 
                ON draws(draw_date DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_issue 
                ON draws(issue DESC)
            """)
            conn.commit()

    def save_draw(self, issue: str, draw_date: str,
                  front: List[int], back: List[int]) -> bool:
        """
        保存一期开奖数据
        Returns: 是否成功保存（False表示已存在）
        """
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("""
                    INSERT INTO draws (issue, draw_date, front_numbers, back_numbers, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    issue,
                    draw_date,
                    json.dumps(front),
                    json.dumps(back),
                    datetime.now().isoformat()
                ))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # 期号已存在
                return False

    def save_draws_batch(self, draws: List[Dict]) -> int:
        """
        批量保存多期数据
        Returns: 实际保存数量（去重后）
        """
        saved = 0
        for draw in draws:
            if self.save_draw(
                draw["issue"],
                draw["draw_date"],
                draw["front"],
                draw["back"]
            ):
                saved += 1
        return saved

    def get_all_draws(self) -> List[Dict]:
        """获取所有历史数据，按期号升序"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT issue, draw_date, front_numbers, back_numbers
                FROM draws
                ORDER BY issue ASC
            """)
            return [{
                "issue": row["issue"],
                "draw_date": row["draw_date"],
                "front": json.loads(row["front_numbers"]),
                "back": json.loads(row["back_numbers"])
            } for row in cursor.fetchall()]

    def get_draws_recent(self, count: int) -> List[Dict]:
        """获取最近N期数据"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT issue, draw_date, front_numbers, back_numbers
                FROM draws
                ORDER BY issue DESC
                LIMIT ?
            """, (count,))
            rows = cursor.fetchall()
            # 返回升序（早期在前）
            return [{
                "issue": row["issue"],
                "draw_date": row["draw_date"],
                "front": json.loads(row["front_numbers"]),
                "back": json.loads(row["back_numbers"])
            } for row in reversed(rows)]

    def get_latest_issue(self) -> Optional[str]:
        """获取最新一期期号"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT issue FROM draws ORDER BY issue DESC LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row else None

    def get_first_issue(self) -> Optional[str]:
        """获取最早一期期号"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT issue FROM draws ORDER BY issue ASC LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row else None

    def count(self) -> int:
        """总期数"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM draws")
            return cursor.fetchone()[0]

    def get_draw_by_issue(self, issue: str) -> Optional[Dict]:
        """按期号查询"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT issue, draw_date, front_numbers, back_numbers
                FROM draws WHERE issue = ?
            """, (issue,))
            row = cursor.fetchone()
            if row:
                return {
                    "issue": row["issue"],
                    "draw_date": row["draw_date"],
                    "front": json.loads(row["front_numbers"]),
                    "back": json.loads(row["back_numbers"])
                }
            return None
