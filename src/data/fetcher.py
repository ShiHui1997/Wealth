"""
大乐透历史数据获取模块
支持多数据源，以50期为一批获取历史数据，直到第一期
"""
import requests
import time
import re
import json
from typing import List, Dict, Optional


class DaletouFetcher:
    """大乐透数据获取器（多数据源容错）"""

    def __init__(self, batch_size: int = 50, delay: float = 1.0):
        self.batch_size = batch_size
        self.delay = delay

        # 自动检测代理（用户环境有 1080 端口代理）
        proxies = None
        try:
            # 快速检测本地是否有可用代理
            test_proxies = [
                {"http": "http://127.0.0.1:1080", "https": "http://127.0.0.1:1080"},
                {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
                {"http": "socks5://127.0.0.1:10808", "https": "socks5://127.0.0.1:10808"},
            ]
            for p in test_proxies:
                try:
                    r = requests.get("https://www.baidu.com",
                                     proxies=p, timeout=3)
                    if r.status_code == 200:
                        proxies = p
                        print(f"[网络] 使用代理: {p['https']}")
                        break
                except Exception:
                    continue
            if not proxies:
                print("[网络] 未检测到可用代理，直连")
        except Exception as e:
            print(f"[网络] 代理检测跳过: {e}")

        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        })
        # 记录已获取的期号，避免重复
        self.fetched_issues = set()

    # ─────────────────────────────────────────
    # 公开方法
    # ─────────────────────────────────────────

    def fetch_latest(self) -> Optional[Dict]:
        """获取最新一期开奖数据"""
        print("[获取最新] 正在获取...")
        result = self._fetch_latest_500api()
        if result:
            return result
        result = self._fetch_latest_500page()
        return result

    def fetch_history_batch(self, batch_num: int) -> List[Dict]:
        """
        获取一批历史数据
        batch_num: 第几批（从1开始）
        Returns: 开奖数据列表
        """
        print(f"[批量获取] 第{batch_num}批...")

        # 策略1：500彩票网API（最可靠）
        results = self._fetch_500_api(batch_num)
        if results:
            unique = []
            for r in results:
                if r["issue"] not in self.fetched_issues:
                    self.fetched_issues.add(r["issue"])
                    unique.append(r)
            print(f"[批量获取] 获取到 {len(unique)} 条（去重后）")
            return unique

        # 策略2：500彩票网页面解析
        results = self._fetch_500_page(batch_num)
        if results:
            unique = []
            for r in results:
                if r["issue"] not in self.fetched_issues:
                    self.fetched_issues.add(r["issue"])
                    unique.append(r)
            print(f"[批量获取] 页面解析到 {len(unique)} 条")
            return unique

        print("[批量获取] 本批无数据（可能已到第一期或所有源都失败）")
        return []

    def set_fetched_issues(self, issues: set):
        """从数据库加载已获取的期号"""
        self.fetched_issues = issues

    # ─────────────────────────────────────────
    # 数据源：500彩票网隐藏API（首选，返回JSON）
    # ─────────────────────────────────────────

    def _fetch_500_api(self, batch_num: int) -> List[Dict]:
        """
        使用500彩票网的隐藏数据接口
        URL: https://datachart.500.com/dlt/history/newinc/outdata.php
        这个接口直接返回CSV格式的开奖数据
        """
        results = []
        try:
            # 500彩票网的隐藏API
            url = "https://datachart.500.com/dlt/history/newinc/outdata.php"
            params = {
                "start": str((batch_num - 1) * self.batch_size + 1),
                "end": str(batch_num * self.batch_size),
            }
            resp = self.session.get(url, params=params, timeout=15)
            resp.encoding = "utf-8"

            if resp.status_code != 200 or len(resp.text.strip()) < 20:
                print(f"[500API] 返回异常: status={resp.status_code}")
                return []

            lines = resp.text.strip().split("\n")
            for line in lines:
                parts = line.split(",")
                if len(parts) < 8:
                    continue
                # 格式: 期号,前区号码(5个),后区号码(2个),奖金,...
                issue = parts[0].strip().replace('"', '')
                if not issue.isdigit() or len(issue) < 6:
                    continue

                front = []
                back = []
                # 前区5个号码在中间位置
                for i in range(1, 6):
                    if i < len(parts):
                        n = parts[i].strip().replace('"', '')
                        if n.isdigit():
                            num = int(n)
                            if 1 <= num <= 35:
                                front.append(num)

                # 后区2个号码
                for i in range(6, 8):
                    if i < len(parts):
                        n = parts[i].strip().replace('"', '')
                        if n.isdigit():
                            num = int(n)
                            if 1 <= num <= 12:
                                back.append(num)

                if len(front) == 5 and len(back) == 2 and issue:
                    results.append({
                        "issue": issue,
                        "draw_date": "",
                        "front": sorted(front),
                        "back": sorted(back),
                    })

            print(f"[500API] 解析到 {len(results)} 条记录")
            return results

        except Exception as e:
            print(f"[500API] 获取失败: {e}")

        return []

    def _fetch_latest_500api(self) -> Optional[Dict]:
        """从500彩票API获取最新一期"""
        try:
            url = "https://datachart.500.com/dlt/history/newinc/outdata.php"
            params = {"start": "1", "end": "1"}
            resp = self.session.get(url, params=params, timeout=10)
            resp.encoding = "utf-8"

            lines = resp.text.strip().split("\n")
            if lines:
                parts = lines[0].split(",")
                if len(parts) >= 8:
                    issue = parts[0].strip().replace('"', '')
                    front = sorted([int(p.strip()) for p in parts[1:6]
                                    if p.strip().isdigit()])
                    back = sorted([int(p.strip()) for p in parts[6:8]
                                   if p.strip().isdigit()])
                    if issue and len(front) == 5 and len(back) == 2:
                        return {
                            "issue": issue,
                            "draw_date": "",
                            "front": front,
                            "back": back,
                        }
        except Exception as e:
            print(f"[500API-最新] 失败: {e}")
        return None

    # ─────────────────────────────────────────
    # 数据源：500彩票网页面解析（备用）
    # ─────────────────────────────────────────

    def _fetch_500_page(self, batch_num: int) -> List[Dict]:
        """从500彩票网页面抓取历史数据"""
        results = []
        try:
            url = f"https://kaijiang.500.com/dlt.shtml"
            if batch_num > 1:
                url += f"?page={batch_num}"

            resp = self.session.get(url, timeout=15)
            resp.encoding = "gb2312"
            text = resp.text

            # 用正则提取开奖行
            # 500彩票网页面中每行开奖数据包含期号和7个号码
            # 模式匹配：期号 + 一串数字（含前后区号码）
            rows = re.findall(
                r'<tr[^>]*>.*?</tr>',
                text,
                re.DOTALL | re.IGNORECASE
            )

            for row in rows:
                # 提取期号
                issue_match = re.search(
                    r'(\d{7})|第(\d{7})\s*期',
                    row.replace("<br>", "").replace("\n", "")
                )
                issue = None
                if issue_match:
                    issue = issue_match.group(1) or issue_match.group(2)

                # 提取所有数字（1~35是前区候选，1~12是后区候选）
                nums = [int(n) for n in re.findall(r'>(\d{2})<', row)]
                valid_nums = [n for n in nums if 1 <= n <= 35]

                if issue and len(valid_nums) >= 7:
                    # 前5个作为前区（可能需要过滤），后2个作为后区
                    front = sorted(valid_nums[:5])
                    # 后区号码应该在1~12之间
                    remaining = [n for n in valid_nums[5:] if 1 <= n <= 12]
                    if len(remaining) < 2:
                        remaining = [n for n in nums if 1 <= n <= 12][:2]
                    back = sorted(remaining[:2]) if remaining else [1, 2]

                    if len(front) == 5 and len(back) == 2:
                        results.append({
                            "issue": issue,
                            "draw_date": "",
                            "front": front,
                            "back": back,
                        })

            if results:
                print(f"[500页面] 解析到 {len(results)} 条")

        except Exception as e:
            print(f"[500页面] 获取失败: {e}")

        return results

    def _fetch_latest_500page(self) -> Optional[Dict]:
        """从500彩票网页面获取最新一期"""
        try:
            resp = self.session.get("https://kaijiang.500.com/dlt.shtml",
                                   timeout=10)
            resp.encoding = "gb2312"
            text = resp.text

            # 找第一个包含完整开奖数据的行
            nums = [int(n) for n in re.findall(r'>(\d{2})<', text)]
            valid_front = [n for n in nums[:7] if 1 <= n <= 35]
            if len(valid_front) >= 5:
                front = sorted(valid_front[:5])
                remaining = [n for n in nums[5:12] if 1 <= n <= 12]
                back = sorted(remaining[:2])

                issue_match = re.search(r'(\d{7})', text[:2000])
                issue = issue_match.group(1) if issue_match else ""

                if issue and len(back) >= 2:
                    return {
                        "issue": issue,
                        "draw_date": "",
                        "front": front,
                        "back": back,
                    }
        except Exception as e:
            print(f"[500页面-最新] 失败: {e}")
        return None

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
