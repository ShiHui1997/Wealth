"""
大乐透数据存储模块
使用 SQLite 存储历史开奖数据、预测记录、验证结果
支持自我迭代：每次预测都记录，每次开奖都验证，用结果校正学习
"""
import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple


class LotteryStorage:
    """大乐透数据存储（含预测记录 + 验证结果）"""

    def __init__(self, db_path: str = "data/daletou.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化所有数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            # 表1: 历史开奖数据
            conn.execute("""
                CREATE TABLE IF NOT EXISTS draws (
                    issue      TEXT PRIMARY KEY,
                    draw_date  TEXT NOT NULL,
                    front_numbers TEXT NOT NULL,
                    back_numbers  TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_draw_date ON draws(draw_date DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_issue   ON draws(issue DESC)")

            # 表2: 预测记录
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_issue TEXT NOT NULL,
                    predicted_at TEXT NOT NULL,
                    rank        INTEGER NOT NULL,
                    front_numbers TEXT NOT NULL,
                    back_numbers  TEXT NOT NULL,
                    similarity_score REAL NOT NULL,
                    model_version  TEXT DEFAULT 'v1',
                    verified    INTEGER DEFAULT 0,
                    front_match_count INTEGER DEFAULT NULL,
                    back_match_count  INTEGER DEFAULT NULL,
                    is_exact_match   INTEGER DEFAULT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_issue
                ON predictions(target_issue, rank)
            """)

            # 表3: 验证汇总（每期开奖后更新）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS verifications (
                    issue           TEXT PRIMARY KEY,
                    verified_at     TEXT NOT NULL,
                    best_front_match INTEGER,
                    best_back_match  INTEGER,
                    any_front_match  INTEGER,
                    any_back_match   INTEGER,
                    avg_similarity   REAL,
                    actual_front     TEXT,
                    actual_back      TEXT
                )
            """)

            # 表4: 批次回归分析记录
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_analysis (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_no     INTEGER NOT NULL,
                    batch_start  TEXT NOT NULL,
                    batch_end    TEXT NOT NULL,
                    analyzed_at  TEXT NOT NULL,
                    feature_diff TEXT NOT NULL,
                    regression_notes TEXT
                )
            """)

            # 表5: 模型校准参数
            conn.execute("""
                CREATE TABLE IF NOT EXISTS calibration (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    updated_at    TEXT NOT NULL,
                    param_name    TEXT NOT NULL UNIQUE,
                    param_value   REAL NOT NULL,
                    note          TEXT
                )
            """)
            conn.commit()

    
    def get_conn(self):
        """返回一个新的 SQLite 连接（供上下文管理器使用）""" 
        return sqlite3.connect(self.db_path)

    # ═══════════════════════════════════════════
    # 开奖数据 CRUD
    # ═══════════════════════════════════════════

    def save_draw(self, issue: str, draw_date: str,
                 front: List[int], back: List[int]) -> bool:
        """保存一期开奖数据，返回是否新插入"""
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("""
                    INSERT INTO draws (issue, draw_date, front_numbers, back_numbers, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (issue, draw_date,
                       json.dumps(front), json.dumps(back),
                       datetime.now().isoformat()))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # 已存在：更新（以防日期等信息有变）
                conn.execute("""
                    UPDATE draws
                    SET draw_date = ?, front_numbers = ?, back_numbers = ?
                    WHERE issue = ?
                """, (draw_date,
                       json.dumps(front), json.dumps(back),
                       issue))
                conn.commit()
                return False

    def save_draws_batch(self, draws: List[Dict]) -> int:
        """批量保存，返回新插入数量"""
        saved = 0
        for draw in draws:
            if self.save_draw(draw["issue"], draw["draw_date"],
                              draw["front"], draw["back"]):
                saved += 1
        return saved

    def get_all_draws(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT issue, draw_date, front_numbers, back_numbers
                FROM draws ORDER BY issue ASC
            """)
            return [{
                "issue": r["issue"], "draw_date": r["draw_date"],
                "front": json.loads(r["front_numbers"]),
                "back":  json.loads(r["back_numbers"]),
            } for r in cursor.fetchall()]

    def get_draws_recent(self, count: int) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT issue, draw_date, front_numbers, back_numbers
                FROM draws ORDER BY issue DESC LIMIT ?
            """, (count,)).fetchall()
            return [{
                "issue": r["issue"], "draw_date": r["draw_date"],
                "front": json.loads(r["front_numbers"]),
                "back":  json.loads(r["back_numbers"]),
            } for r in reversed(rows)]

    def get_draws_range(self, start_issue: str, end_issue: str) -> List[Dict]:
        """获取指定期号范围内的数据（含起止）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT issue, draw_date, front_numbers, back_numbers
                FROM draws
                WHERE issue >= ? AND issue <= ?
                ORDER BY issue ASC
            """, (start_issue, end_issue)).fetchall()
            return [{
                "issue": r["issue"], "draw_date": r["draw_date"],
                "front": json.loads(r["front_numbers"]),
                "back":  json.loads(r["back_numbers"]),
            } for r in rows]

    def get_latest_issue(self) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            r = conn.execute("SELECT issue FROM draws ORDER BY issue DESC LIMIT 1").fetchone()
            return r[0] if r else None

    def get_first_issue(self) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            r = conn.execute("SELECT issue FROM draws ORDER BY issue ASC LIMIT 1").fetchone()
            return r[0] if r else None

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]

    def get_draw_by_issue(self, issue: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                "SELECT * FROM draws WHERE issue = ?", (issue,)
            ).fetchone()
            if r:
                return {
                    "issue": r["issue"], "draw_date": r["draw_date"],
                    "front": json.loads(r["front_numbers"]),
                    "back":  json.loads(r["back_numbers"]),
                }
            return None

    # ═══════════════════════════════════════════
    # 预测记录 CRUD
    # ═══════════════════════════════════════════

    def save_prediction(self, target_issue: str,
                       predictions: List[Tuple[Dict, float]],
                       model_version: str = "v1") -> None:
        """
        保存一次预测结果（3注）
        predictions: [(num_dict, similarity_score), ...] 按得分降序
        """
        with sqlite3.connect(self.db_path) as conn:
            for rank, (nums, score) in enumerate(predictions, 1):
                conn.execute("""
                    INSERT INTO predictions
                    (target_issue, predicted_at, rank,
                     front_numbers, back_numbers, similarity_score, model_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    target_issue,
                    datetime.now().isoformat(),
                    rank,
                    json.dumps(nums["front"]),
                    json.dumps(nums["back"]),
                    score,
                    model_version,
                ))
            conn.commit()

    def get_predictions_by_issue(self, issue: str) -> List[Dict]:
        """获取某期的所有预测记录"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM predictions
                WHERE target_issue = ?
                ORDER BY rank ASC
            """, (issue,)).fetchall()
            return [dict(r) for r in rows]

    def get_latest_prediction(self) -> Optional[Dict]:
        """获取最近一次预测（用于等待开奖后验证）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            r = conn.execute("""
                SELECT target_issue FROM predictions
                ORDER BY predicted_at DESC LIMIT 1
            """).fetchone()
            return dict(r) if r else None

    # ═══════════════════════════════════════════
    # 验证：比对预测 vs 真实开奖
    # ═══════════════════════════════════════════

    def verify_prediction(self, issue: str) -> Optional[Dict]:
        """
        用某期真实开奖数据验证该期预测
        返回验证结果摘要，并更新数据库
        """
        # 获取真实开奖
        actual = self.get_draw_by_issue(issue)
        if not actual:
            print(f"[验证] 期号 {issue} 暂无开奖数据，跳过")
            return None

        # 获取该期预测
        preds = self.get_predictions_by_issue(issue)
        if not preds:
            print(f"[验证] 期号 {issue} 无预测记录，跳过")
            return None

        actual_front = set(actual["front"])
        actual_back = set(actual["back"])

        best_front_match = 0
        best_back_match = 0
        any_front_3plus = 0
        any_back_1plus = 0

        with sqlite3.connect(self.db_path) as conn:
            for pred in preds:
                pred_front = set(json.loads(pred["front_numbers"]))
                pred_back = set(json.loads(pred["back_numbers"]))

                f_match = len(pred_front & actual_front)
                b_match = len(pred_back & actual_back)

                # 更新该条预测的命中情况
                conn.execute("""
                    UPDATE predictions
                    SET verified = 1,
                        front_match_count = ?,
                        back_match_count = ?,
                        is_exact_match = ?
                    WHERE id = ?
                """, (f_match, b_match,
                       1 if (f_match == 5 and b_match == 2) else 0,
                       pred["id"]))

                best_front_match = max(best_front_match, f_match)
                best_back_match = max(best_back_match, b_match)
                if f_match >= 3:
                    any_front_3plus = 1
                if b_match >= 1:
                    any_back_1plus = 1

            # 写入验证汇总
            avg_sim = sum(p.get("similarity_score", 0) for p in preds) / len(preds)
            conn.execute("""
                INSERT OR REPLACE INTO verifications
                (issue, verified_at, best_front_match, best_back_match,
                 any_front_match, any_back_match, avg_similarity,
                 actual_front, actual_back)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (issue, datetime.now().isoformat(),
                   best_front_match, best_back_match,
                   any_front_3plus, any_back_1plus,
                   avg_sim,
                   json.dumps(actual["front"]),
                   json.dumps(actual["back"])))
            conn.commit()

        result = {
            "issue": issue,
            "actual_front": actual["front"],
            "actual_back": actual["back"],
            "best_front_match": best_front_match,
            "best_back_match": best_back_match,
            "any_front_3plus": bool(any_front_3plus),
            "any_back_1plus": bool(any_back_1plus),
            "predictions": preds,
        }
        self._print_verification(result)
        return result

    def _print_verification(self, result: Dict):
        """打印验证结果（格式化输出）"""
        print(f"\n{'='*50}")
        print(f"[验证结果] 第 {result['issue']} 期")
        print(f"  真实开奖: 前区 {result['actual_front']}  后区 {result['actual_back']}")
        print(f"  最佳命中: 前区 {result['best_front_match']}/5  后区 {result['best_back_match']}/2")
        print(f"  是否有注前区命中≥3: {'是' if result['any_front_3plus'] else '否'}")
        print(f"  是否有注后区命中≥1: {'是' if result['any_back_1plus'] else '否'}")
        for pred in result["predictions"]:
            f = json.loads(pred["front_numbers"])
            b = json.loads(pred["back_numbers"])
            fm = pred.get("front_match_count", 0)
            bm = pred.get("back_match_count", 0)
            print(f"  第{pred['rank']}注: 前区{f} 后区{b}  "
                  f"→ 前区命中{fm} 后区命中{bm}")
        print(f"{'='*50}\n")

    def verify_latest(self) -> Optional[Dict]:
        """验证最新一期（获取最新开奖后自动调用）"""
        latest_issue = self.get_latest_issue()
        if not latest_issue:
            return None
        return self.verify_prediction(latest_issue)

    # ═══════════════════════════════════════════
    # 批次回归分析记录
    # ═══════════════════════════════════════════

    def save_batch_analysis(self, batch_no: int,
                           batch_start: str, batch_end: str,
                           feature_diff: Dict, notes: str):
        """保存一批数据的回归分析结果"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO batch_analysis
                (batch_no, batch_start, batch_end,
                 analyzed_at, feature_diff, regression_notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (batch_no, batch_start, batch_end,
                   datetime.now().isoformat(),
                   json.dumps(feature_diff, ensure_ascii=False),
                   notes))
            conn.commit()

    def get_batch_analyses(self) -> List[Dict]:
        """获取所有批次分析记录"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM batch_analysis ORDER BY batch_no ASC"
            ).fetchall()]

    # ═══════════════════════════════════════════
    # 模型校准参数（自我学习结果持久化）
    # ═══════════════════════════════════════════

    def save_calibration(self, param_name: str, param_value: float, note: str = ""):
        """保存/更新校准参数"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO calibration (updated_at, param_name, param_value, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(param_name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    param_value = excluded.param_value,
                    note = excluded.note
            """, (datetime.now().isoformat(), param_name, param_value, note))
            conn.commit()

    def get_calibration(self, param_name: str) -> Optional[float]:
        """读取校准参数"""
        with sqlite3.connect(self.db_path) as conn:
            r = conn.execute(
                "SELECT param_value FROM calibration WHERE param_name = ?",
                (param_name,)
            ).fetchone()
            return r[0] if r else None

    def get_all_calibrations(self) -> Dict[str, float]:
        """读取所有校准参数"""
        with sqlite3.connect(self.db_path) as conn:
            return dict(conn.execute(
                "SELECT param_name, param_value FROM calibration"
            ).fetchall())

    # ═══════════════════════════════════════════
    # 统计：预测效果汇总
    # ═══════════════════════════════════════════

    def get_verification_stats(self) -> Dict:
        """汇总所有验证结果，用于评估预测效果"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM verifications ORDER BY issue ASC").fetchall()
            if not rows:
                return {"total_verified": 0}

            rows = [dict(r) for r in rows]

            total = len(rows)
            front_dist = {}  # 前区命中数分布
            back_dist = {}
            for r in rows:
                f = r["best_front_match"]
                b = r["best_back_match"]
                front_dist[f] = front_dist.get(f, 0) + 1
                back_dist[b] = back_dist.get(b, 0) + 1

            return {
                "total_verified": total,
                "front_match_dist": front_dist,
                "back_match_dist": back_dist,
                "any_front_3plus_rate": sum(r["any_front_match"] for r in rows) / total,
                "any_back_1plus_rate": sum(r["any_back_match"] for r in rows) / total,
                "recent_issues": [r["issue"] for r in rows[-10:]],
            }


    # ═════════════════════════════════════════════
    # 验证详情（供校准模块使用）
    # ═════════════════════════════════════════════

    def get_verification_details(self) -> list:
        """获取所有验证详情，供校准模块分析使用"""
        import json
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT v.issue, v.best_front_match, v.best_back_match,
                       v.avg_similarity, v.actual_front, v.actual_back,
                       v.any_front_match, v.any_back_match
                FROM verifications v
                ORDER BY v.issue ASC
            """).fetchall()
            return [{
                "issue": r["issue"],
                "front_match": r["best_front_match"],
                "back_match": r["best_back_match"],
                "avg_similarity": r["avg_similarity"],
                "actual_front": json.loads(r["actual_front"]),
                "actual_back": json.loads(r["actual_back"]),
                "any_front_3plus": bool(r["any_front_match"]),
                "any_back_1plus": bool(r["any_back_match"]),
            } for r in rows]

    # ══════════════════════════════════════════
    # 校准次数 & 当前种子（用于自动种子轮换）
    # ══════════════════════════════════════════

    def get_calibration_count(self) -> int:
        """读取已完成的校准次数（用于计算种子偏移）"""
        with sqlite3.connect(self.db_path) as conn:
            r = conn.execute(
                "SELECT param_value FROM calibration WHERE param_name = 'calibration_count'"
            ).fetchone()
            return int(r[0]) if r else 0

    def incr_calibration_count(self) -> int:
        """校准次数 +1，返回新的次数"""
        count = self.get_calibration_count() + 1
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO calibration (updated_at, param_name, param_value, note)
                VALUES (?, 'calibration_count', ?, ?)
                ON CONFLICT(param_name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    param_value = excluded.param_value,
                    note = excluded.note
            """, (datetime.now().isoformat(), float(count), f"第{count}次校准"))
            conn.commit()
        return count

    def get_current_seed(self) -> int:
        """读取当前预测用的随机种子（默认42）"""
        with sqlite3.connect(self.db_path) as conn:
            r = conn.execute(
                "SELECT param_value FROM calibration WHERE param_name = 'current_seed'"
            ).fetchone()
            return int(r[0]) if r else 42

    def set_current_seed(self, seed: int):
        """写入当前种子到数据库"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO calibration (updated_at, param_name, param_value, note)
                VALUES (?, 'current_seed', ?, ?)
                ON CONFLICT(param_name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    param_value = excluded.param_value,
                    note = excluded.note
            """, (datetime.now().isoformat(), float(seed), f"种子={seed}"))
            conn.commit()

    def get_all_predicted_issues(self) -> set:
        """返回所有有预测记录的期号集合（用于自动补验证）"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT target_issue FROM predictions"
            ).fetchall()
            return {r[0] for r in rows}

    def get_all_verified_issues(self) -> set:
        """返回所有已验证的期号集合"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT issue FROM verifications"
            ).fetchall()
            return {r[0] for r in rows}

    def load_from_seed(self, seed_path: str) -> int:
        """
        从JSON种子文件加载历史开奖数据（用于GitHub Actions等无法访问体彩API的环境）
        返回成功导入的记录数
        """
        import json as _json
        with open(seed_path, "r", encoding="utf-8") as f:
            data = _json.load(f)

        if isinstance(data, list):
            draws = data
        elif isinstance(data, dict) and "draws" in data:
            draws = data["draws"]
        else:
            raise ValueError(f"种子文件格式错误: 期望list或{{draws: [...]}}")

        count = 0
        for d in draws:
            issue = d.get("issue", "")
            draw_date = d.get("draw_date", "")
            front = d.get("front", [])
            back = d.get("back", [])
            if not issue or not front or not back:
                continue
            if self.save_draw(issue, draw_date, front, back):
                count += 1

        total = self.count()
        first = self.get_first_issue()
        last = self.get_latest_issue()
        print(f"[种子加载] 导入 {count} 条新记录，总计 {total} 期 ({first} ~ {last})")
        return count
