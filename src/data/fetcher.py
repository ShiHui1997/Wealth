"""
大乐透历史数据获取模块
支持多数据源，以50期为一批获取历史数据，直到第一期
"""
import requests
import time
import re
import json
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

# 大乐透自2007年开始发行，期号格式：年份+3位序号，如2007001
# 前区：01-35选5，后区：01-12选2


class DaletouFetcher:
    """大乐透数据获取器（多数据源容错）"""

    def __init__(self, batch_size: int = 50, delay: float = 1.0):
        self.batch_size = batch_size
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
        # 先尝试500彩票网首页
        result = self._fetch_latest_500()
        if result:
            return result
        # 再尝试搜狐彩票
        result = self._fetch_latest_souhu()
        return result

    def fetch_history_batch(self, batch_num: int) -> List[Dict]:
        """
        获取一批历史数据
        batch_num: 第几批（从1开始）
        策略：从最新往历史方向获取
        Returns: 开奖数据列表（按日期升序）
        """
        print(f"[批量获取] 第{batch_num}批...")

        # 策略1：从500彩票网历史页面获取
        results = self._fetch_batch_500_desc(batch_num)
        if results:
            # 去重
            unique = []
            for r in results:
                if r["issue"] not in self.fetched_issues:
                    self.fetched_issues.add(r["issue"])
                    unique.append(r)
            print(f"[批量获取] 500彩票网获取到 {len(unique)} 条（去重后）")
            return unique

        # 策略2：从官方网站获取
        results = self._fetch_batch_official(batch_num)
        if results:
            unique = []
            for r in results:
                if r["issue"] not in self.fetched_issues:
                    self.fetched_issues.add(r["issue"])
                    unique.append(r)
            print(f"[批量获取] 官方API获取到 {len(unique)} 条")
            return unique

        print("[批量获取] 本批无数据（可能已到第一期）")
        return []

    def set_fetched_issues(self, issues: set):
        """从数据库加载已获取的期号（避免重复获取）"""
        self.fetched_issues = issues

    # ─────────────────────────────────────────
    # 数据源：500彩票网（主要数据源）
    # ─────────────────────────────────────────

    def _fetch_latest_500(self) -> Optional[Dict]:
        """从500彩票网获取最新一期"""
        try:
            url = "https://kaijiang.500.com/dlt.shtml"
            resp = self.session.get(url, timeout=15)
            resp.encoding = "gb2312"
            soup = BeautifulSoup(resp.text, "html.parser")

            # 找最新开奖信息
            # 500彩票网的结构：最新开奖在页面上方
            # 用多种方式尝试解析
            issue = None
            front = []
            back = []

            # 方式1：找 class 包含 ball 的标签
            ball_ems = soup.find_all("em")
            if len(ball_ems) >= 7:
                # 前5个是前区，后2个是后区
                nums = [int(e.text.strip()) for e in ball_ems[:7]]
                front = nums[:5]
                back = nums[5:7]
                # 找期号
                issue_tag = soup.find("font", class_=re.compile("cfont"))
                if issue_tag:
                    issue = issue_tag.text.strip()

            if issue and len(front) == 5 and len(back) == 2:
                return {
                    "issue": issue,
                    "draw_date": "",
                    "front": sorted(front),
                    "back": sorted(back),
                }
        except Exception as e:
            print(f"[500彩票-最新] 获取失败: {e}")
        return None

    def _fetch_batch_500_desc(self, batch_num: int) -> List[Dict]:
        """
        从500彩票网按页获取历史数据
        500彩票网大乐透历史页面支持分页
        URL格式：https://kaijiang.500.com/dlt.shtml?page=2
        """
        results = []
        try:
            # 计算页码（每页大约50条）
            page = batch_num

            url = f"https://kaijiang.500.com/dlt.shtml"
            if page > 1:
                url += f"?page={page}"

            resp = self.session.get(url, timeout=15)
            resp.encoding = "gb2312"
            soup = BeautifulSoup(resp.text, "html.parser")

            # 找开奖表格
            # 500彩票网的表格结构比较复杂，尝试多种方式
            results = self._parse_500_table(soup)
            if results:
                return results

            # 如果表格解析失败，尝试解析页面中的所有开奖条目
            results = self._parse_500_items(soup)
            return results

        except Exception as e:
            print(f"[500彩票-批量] 获取失败: {e}")
        return []

    def _parse_500_table(self, soup: BeautifulSoup) -> List[Dict]:
        """解析500彩票网的表格数据"""
        results = []
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # 跳过表头
                cells = row.find_all(["td", "th"])
                if len(cells) < 8:
                    continue

                # 尝试从cells中提取数据
                issue = None
                draw_date = ""
                front = []
                back = []

                # 找期号（通常在第一列）
                for cell in cells[:3]:
                    text = cell.text.strip()
                    if re.match(r"\d{7,8}", text):
                        issue = text
                        break

                # 找号码球
                ball_tags = row.find_all(["em", "span"])
                nums = []
                for tag in ball_tags:
                    text = tag.text.strip()
                    if re.match(r"\d{1,2}", text):
                        num = int(text)
                        if 1 <= num <= 35:
                            nums.append(num)

                if len(nums) >= 7:
                    front = sorted(nums[:5])
                    back = sorted(nums[5:7])
                elif len(nums) == 5:
                    # 只有前区，后区需要从其他地方找
                    front = sorted(nums)
                    # 尝试从remaining cells找后区
                    for cell in cells:
                        cell_nums = re.findall(r"\d{2}", cell.text)
                        if len(cell_nums) >= 2:
                            back = sorted([int(n) for n in cell_nums[:2]])
                            break

                if issue and len(front) == 5 and len(back) == 2:
                    results.append({
                        "issue": issue,
                        "draw_date": draw_date,
                        "front": front,
                        "back": back,
                    })

        return results

    def _parse_500_items(self, soup: BeautifulSoup) -> List[Dict]:
        """解析页面中的开奖条目（非表格形式）"""
        results = []
        # 找所有包含期号和号码的块
        items = soup.find_all(["div", "li"], class_=re.compile("ball|kj|item"))
        for item in items:
            text = item.text
            issue_match = re.search(r"第?\s*(\d{7,8})\s*期?", text)
            if not issue_match:
                continue
            issue = issue_match.group(1)
            nums = re.findall(r"\b(\d{1,2})\b", text)
            nums = [int(n) for n in nums if 1 <= int(n) <= 35]
            if len(nums) >= 5:
                results.append({
                    "issue": issue,
                    "draw_date": "",
                    "front": sorted(nums[:5]),
                    "back": sorted(nums[5:7]) if len(nums) >= 7 else [nums[5], nums[6]] if len(nums) >= 7 else [1, 2],
                })
        return results

    def _fetch_latest_souhu(self) -> Optional[Dict]:
        """从搜狐彩票获取最新开奖（备用数据源）"""
        try:
            url = "https://caipiao.sogou.com/dlt.htm"
            resp = self.session.get(url, timeout=10)
            # 解析...
        except Exception as e:
            print(f"[搜狐彩票] 获取失败: {e}")
        return None

    # ─────────────────────────────────────────
    # 数据源：中国体彩网官方（备用）
    # ─────────────────────────────────────────

    def _fetch_batch_official(self, batch_num: int) -> List[Dict]:
        """
        从官方API获取历史数据
        中国体彩网有部分公开的API接口
        """
        results = []
        try:
            # 尝试官方查询接口
            # 注：官方接口可能需要cookie或token
            url = "http://www.lottery.gov.cn/kjy/wqkjgg.do"
            params = {
                "ltype": "dlt",
                "page": batch_num,
                "rows": self.batch_size,
            }
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    return self._parse_official_json(data)
                except Exception:
                    pass
        except Exception as e:
            print(f"[官方API] 获取失败: {e}")
        return results

    def _parse_official_json(self, data: dict) -> List[Dict]:
        """解析官方API返回的JSON"""
        results = []
        items = data.get("data", data.get("rows", []))
        for item in items:
            issue = str(item.get("issue", item.get("qihao", "")))
            draw_date = item.get("date", item.get("riqi", ""))
            front = [int(x) for x in item.get("front", item.get("qianqu", []))]
            back = [int(x) for x in item.get("back", item.get("houqu", []))]
            if len(front) == 5 and len(back) == 2:
                results.append({
                    "issue": issue,
                    "draw_date": draw_date,
                    "front": sorted(front),
                    "back": sorted(back),
                })
        return results

    # ─────────────────────────────────────────
    # 本地种子数据（初次建库用）
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
