"""
大乐透历史数据获取模块
数据源：彩经网 cjcp.com.cn（国内直连，无需代理）
支持按期号逐条获取，以50期为一批，直到第一期(2007001)
"""
import re
import json
import time
import socket
from typing import List, Dict, Optional

import requests


class DaletouFetcher:
    """大乐透数据获取器 — 基于彩经网"""

    # 大乐透首期号
    FIRST_ISSUE = 2007001

    # 彩经网URL模板
    BASE_URL = "https://www.cjcp.com.cn/kaijiang/dlt/index.php?qh={issue}"
    LATEST_URL = "http://www.cjcp.com.cn/dlt/kaijiang/"

    def __init__(self, batch_size: int = 50, delay: float = 0.3):
        self.batch_size = batch_size
        self.delay = delay
        self.fetched_issues = set()

        # 创建会话（不需要代理，国内直连）
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    # ─────────────────────────────────────────
    # 公开方法
    # ─────────────────────────────────────────

    def fetch_latest(self) -> Optional[Dict]:
        """获取最新一期开奖数据"""
        print("[获取最新] 正在从彩经网获取...")

        try:
            resp = self.session.get(self.LATEST_URL, timeout=15)
            result = self._parse_page(resp.text)
            if result:
                print(f"[获取最新] ✓ {result['issue']}: "
                      f"{result['front']} + {result['back']}")
            return result
        except Exception as e:
            print(f"[获取最新] 失败: {e}")
        return None

    def fetch_history_batch(self, batch_num: int) -> List[Dict]:
        """
        获取一批历史数据
        batch_num: 第几批（从1开始）
        每批 self.batch_size 期，按期号倒序排列
        """
        # 先确定当前最新一期
        latest = self._get_latest_issue_num()
        if not latest:
            print("[批量获取] 无法获取最新期号")
            return []

        # 计算本批的起止期号（从新到旧）
        start_issue = latest - (batch_num - 1) * self.batch_size
        end_issue = max(latest - batch_num * self.batch_size + 1,
                        self.FIRST_ISSUE)

        if start_issue < self.FIRST_ISSUE:
            print("[批量获取] 已到达第一期")
            return []

        total = start_issue - end_issue + 1
        print(f"[批量获取] 第{batch_num}批: "
              f"{start_issue} ~ {end_issue} 期（共{total}期）")

        results = []
        fail_count = 0

        for issue_num in range(start_issue, end_issue - 1, -1):
            if str(issue_num) in self.fetched_issues:
                continue

            try:
                url = self.BASE_URL.format(issue=str(issue_num))
                resp = self.session.get(url, timeout=10)
                record = self._parse_page(resp.text)

                if record:
                    self.fetched_issues.add(record["issue"])
                    results.append(record)
                    # 简洁进度
                    if len(results) % 10 == 0 or len(results) <= 3:
                        print(f"  [{len(results)}/{total}] {record['issue']}: "
                              f"{record['front']}+{record['back']}")

                    if self.delay > 0:
                        time.sleep(self.delay)
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                if fail_count <= 2:
                    print(f"  [失败] {issue_num}: {e}")

        print(f"[批量获取] 完成：成功{len(results)}期，"
              f"失败{fail_count}期")
        return results

    def fetch_all_remaining(self) -> List[Dict]:
        """
        获取所有剩余的历史数据（直到第一期）
        自动分批调用 fetch_history_batch
        """
        all_results = []
        batch = 1
        while True:
            batch_data = self.fetch_history_batch(batch)
            if not batch_data:
                break
            all_results.extend(batch_data)
            if len(batch_data) < self.batch_size:
                break  # 最后一批不足，说明到底了
            batch += 1
        return all_results

    def set_fetched_issues(self, issues: set):
        """从数据库加载已获取的期号，避免重复"""
        self.fetched_issues = set(issues)

    # ─────────────────────────────────────────
    # 解析逻辑
    # ─────────────────────────────────────────

    def _parse_page(self, html: str) -> Optional[Dict]:
        """从彩经网HTML页面中解析出一期开奖数据"""
        # 提取号码区块
        block_match = re.search(
            r'num_div.*?((?:<span[^>]*>\s*\d{2}\s*</span>\s*)+)',
            html,
            re.DOTALL,
        )
        if not block_match:
            return None

        all_nums_str = re.findall(r'>(\d{2})<', block_match.group(1))
        if len(all_nums_str) < 7:
            return None

        front = []
        back = []
        for n_s in all_nums_str:
            n = int(n_s)
            if 1 <= n <= 35 and len(front) < 5:
                front.append(n)
            elif 1 <= n <= 12 and len(back) < 2:
                back.append(n)

        if len(front) != 5 or len(back) != 2:
            return None

        # 提取期号
        issue_match = re.search(r'(20[0-2]\d{5})\s*期', html)
        issue = issue_match.group(1) if issue_match else ""

        # 提取日期
        date_match = re.search(
            r'(\d{4})-(\d{2})-(\d{2})', html[:3000]
        )

        return {
            "issue": issue,
            "draw_date": date_match.group(0) if date_match else "",
            "front": sorted(front),
            "back": sorted(back),
        }

    def _get_latest_issue_num(self) -> int:
        """从主页面提取最新一期号"""
        try:
            resp = self.session.get(self.LATEST_URL, timeout=10)
            m = re.search(r'(20\d{5})\s*期', resp.text)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        # 返回一个较新的默认值
        return 2026100

    # ─────────────────────────────────────────
    # 本地种子数据
    # ─────────────────────────────────────────

    def load_local_seed(self, filepath: str) -> List[Dict]:
        """从本地JSON文件加载种子数据"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "draws" in data:
                return data["draws"]
        except Exception as e:
            print(f"[本地种子] 读取失败: {e}")
        return []
