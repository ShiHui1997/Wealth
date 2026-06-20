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
    """大乐透数据获取器（多数据源）"""

    def __init__(self, batch_size: int = 50, delay: float = 1.0):
        self.batch_size = batch_size
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    # ─────────────────────────────────────────────
    # 数据源1: 中国体彩网官方API（最可靠）
    # ─────────────────────────────────────────────
    def _fetch_batch_official(self, page: int = 1) -> List[Dict]:
        """
        从中国体彩网获取批量数据
        API: https://www.lottery.gov.cn/kjy/wqkjgg.do
        注意：这个接口可能需要调整，以实际可访问的为准
        """
        url = "https://www.lottery.gov.cn/kjy/wqkjgg.do"
        params = {
            "_ltype": "dlt",   # 大乐透类型
            "page": page,
            "rows": self.batch_size,
        }
        try:
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return self._parse_official_response(data)
        except Exception as e:
            print(f"[数据源-官方] 获取失败: {e}")
        return []

    # ─────────────────────────────────────────────
    # 数据源2: 500彩票网（HTML解析）
    # ─────────────────────────────────────────────
    def _fetch_batch_500(self, start_issue: str = None) -> List[Dict]:
        """
        从500彩票网获取历史数据
        URL: https://kaijiang.500.com/dlt.shtml
        支持按期号查询
        """
        results = []
        try:
            # 500彩票网大乐透历史页面
            url = "https://kaijiang.500.com/dlt.shtml"
            resp = self.session.get(url, timeout=15)
            resp.encoding = "gb2312"
            soup = BeautifulSoup(resp.text, "html.parser")

            # 解析开奖表格
            table = soup.find("table", class_="kjtb")
            if not table:
                # 尝试其他选择器
                table = soup.find_all("table")[1] if len(soup.find_all("table")) > 1 else None
            if not table:
                return []

            for row in table.find_all("tr")[1:]:  # 跳过表头
                cells = row.find_all("td")
                if len(cells) < 10:
                    continue
                issue = cells[0].text.strip()
                draw_date = cells[1].text.strip()

                # 前区5个号码 + 后区2个号码
                front = []
                back = []
                # 从cells中提取红球（前区）和蓝球（后区）
                ball_tags = row.find_all("em") or row.find_all("span", class_=re.compile("ball"))
                if not ball_tags:
                    # 直接从文本解析
                    nums = re.findall(r'\d{2}', cells[2].text)
                    if len(nums) >= 7:
                        front = [int(n) for n in nums[:5]]
                        back = [int(n) for n in nums[5:7]]
                else:
                    # 用CSS类名区分前后区
                    for ball in ball_tags:
                        num = int(ball.text.strip())
                        cls = ball.get("class", [""])[0]
                        if "red" in cls or "front" in cls:
                            front.append(num)
                        elif "blue" in cls or "back" in cls:
                            back.append(num)

                if len(front) == 5 and len(back) == 2:
                    results.append({
                        "issue": issue,
                        "draw_date": draw_date,
                        "front": sorted(front),
                        "back": sorted(back),
                    })
                if len(results) >= self.batch_size:
                    break
        except Exception as e:
            print(f"[数据源-500彩票] 获取失败: {e}")
        return results

    # ─────────────────────────────────────────────
    # 数据源3: 网易彩票API
    # ─────────────────────────────────────────────
    def _fetch_batch_163(self, count: int = 50) -> List[Dict]:
        """
        从网易彩票获取数据
        API: https://caipiao.163.com/award/dlt/
        """
        results = []
        try:
            url = f"https://caipiao.163.com/award/dlt/"
            resp = self.session.get(url, timeout=15)
            # 网易的数据通常在页面中，需要解析
            # 这里提供一个框架，具体解析根据实际情况调整
            print(f"[数据源-网易] 尝试获取...")
        except Exception as e:
            print(f"[数据源-网易] 获取失败: {e}")
        return results

    # ─────────────────────────────────────────────
    # 数据源4: 本地JSON文件（离线数据）
    # ─────────────────────────────────────────────
    def load_local_seed(self, filepath: str) -> List[Dict]:
        """从本地JSON文件加载种子数据（初次建库用）"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"[本地种子] 读取失败: {e}")
            return []

    # ─────────────────────────────────────────────
    # 统一获取接口
    # ─────────────────────────────────────────────
    def fetch_latest(self) -> Optional[Dict]:
        """获取最新一期开奖数据"""
        # 先尝试500彩票网首页的最新开奖
        try:
            url = "https://kaijiang.500.com/dlt.shtml"
            resp = self.session.get(url, timeout=15)
            resp.encoding = "gb2312"
            soup = BeautifulSoup(resp.text, "html.parser")

            # 找最新一期
            latest_div = soup.find("div", class_="kjxq_box01")
            if latest_div:
                issue = latest_div.find("font", class_="cfont2")
                nums = latest_div.find_all("em")
                if issue and len(nums) >= 7:
                    return {
                        "issue": issue.text.strip(),
                        "draw_date": "",  # 需要额外解析
                        "front": sorted([int(nums[i].text) for i in range(5)]),
                        "back": sorted([int(nums[i].text) for i in range(5, 7)]),
                    }
        except Exception as e:
            print(f"[最新数据] 获取失败: {e}")
        return None

    def fetch_history_batch(self, batch_num: int) -> List[Dict]:
        """
        获取一批历史数据
        batch_num: 第几批（从0开始或1开始，按数据源要求）
        Returns: 开奖数据列表
        """
        # 按优先级尝试各数据源
        sources = [
            ("500彩票网", self._fetch_batch_500),
            ("官方API", lambda _: self._fetch_batch_official(batch_num)),
        ]

        for name, func in sources:
            print(f"[数据获取] 尝试数据源: {name}")
            try:
                data = func(batch_num) if name != "500彩票网" else func(None)
                if data:
                    print(f"[数据获取] {name} 成功获取 {len(data)} 条")
                    return data
            except Exception as e:
                print(f"[数据获取] {name} 异常: {e}")
            time.sleep(self.delay)

        print("[数据获取] 所有数据源均失败")
        return []

    def fetch_all_history(self, storage, on_progress=None):
        """
        持续获取历史数据，直到数据库已有第一期
        或无法获取更多数据为止
        以50期为一批，逐批获取

        storage: LotteryStorage 实例
        on_progress: 进度回调函数
        """
        print("[全量获取] 开始...")
        existing_latest = storage.get_latest_issue()
        print(f"[全量获取] 当前数据库最新期号: {existing_latest}")

        total_new = 0
        batch_count = 0

        while True:
            batch_count += 1
            print(f"\n[全量获取] 第{batch_count}批（每批{self.batch_size}期）")

            # 获取一批数据
            batch_data = self.fetch_history_batch(batch_count)
            if not batch_data:
                print("[全量获取] 无更多数据，停止")
                break

            # 去重后保存
            new_count = storage.save_draws_batch(batch_data)
            total_new += new_count
            print(f"[全量获取] 本批新增 {new_count} 期，累计新增 {total_new} 期")

            if on_progress:
                on_progress(batch_count, new_count, total_new)

            # 如果本批没有新数据，说明已经到头了
            if new_count == 0:
                print("[全量获取] 已无新数据")
                break

            # 检查是否已有第一期（大乐透第1期）
            first = storage.get_first_issue()
            if first and (first.endswith("001") or first == "07001"):
                print(f"[全量获取] 已获取到第一期: {first}")
                break

            time.sleep(self.delay)

        print(f"\n[全量获取] 完成！共新增 {total_new} 期")
        return total_new

    def _parse_official_response(self, data: dict) -> List[Dict]:
        """解析官方API响应（待根据实际API调整）"""
        results = []
        # 这里的解析逻辑需要根据实际API返回格式调整
        if "data" in data:
            for item in data["data"]:
                results.append({
                    "issue": item.get("issue", ""),
                    "draw_date": item.get("date", ""),
                    "front": [int(x) for x in item.get("front", [])],
                    "back": [int(x) for x in item.get("back", [])],
                })
        return results
