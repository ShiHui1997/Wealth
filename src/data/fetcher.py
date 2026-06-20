"""
大乐透历史数据获取模块
数据源：中国体彩官方 API (webapi.sporttery.cn)
  - 返回标准 JSON，无需解析 HTML
  - 国内直连，稳定可靠（已验证可用）
  - 共 97 页、2885 条记录（首期 07001 ~ 最新期）

使用方式：
  1. 首次运行 fetch_all()  → 分页拉取全部历史（约需2-3分钟）
  2. 之后每次运行 fetch_latest() → 只拉最新一期，有新就追加
"""
import time
from typing import List, Dict, Optional

import requests


class DaletouFetcher:
    """大乐透数据获取器 — 基于体彩官方API"""

    # 大乐透在体彩系统中的游戏编号
    GAME_NO = "85"
    PAGE_SIZE = 30  # 每页最多30条

    # 官方API地址
    API_URL = (
        "https://webapi.sporttery.cn/gateway/lottery/"
        "getHistoryPageListV1.qry"
    )

    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Referer": "https://www.cwl.gov.cn/",
        })

    # ─────────────────────────────────────────
    # 公开方法
    # ─────────────────────────────────────────

    def fetch_latest(self) -> Optional[Dict]:
        """
        获取最新一期开奖数据（用于日常增量更新）
        返回标准格式字典，失败返回 None
        """
        print("[获取最新] 正在从体彩官方API获取...")

        try:
            data = self._request_page(page_no=1, page_size=1)
            items = data.get("value", {}).get("list", [])
            if not items:
                print("[获取最新] API返回无数据")
                return None

            record = self._parse_item(items[0])
            if record:
                print(f"[获取最新] {record['issue']}: "
                      f"{record['front']} + {record['back']}")
            return record
        except Exception as e:
            print(f"[获取最新] 失败: {e}")
        return None

    def fetch_all(self) -> List[Dict]:
        """
        获取全部历史开奖数据（从首期到最新期）
        分页请求，每页30条，共约97页
        适合首次运行时一次性拉完所有历史记录
        返回按期号升序排列的完整列表
        """
        print("[全量获取] 正在从体彩官方API获取全部历史数据...")
        print(f"[全量获取] 请求间隔: {self.delay}秒/页")

        try:
            first_page = self._request_page(page_no=1, page_size=self.PAGE_SIZE)
        except Exception as e:
            print(f"[全量获取] 连接失败: {e}")
            return []

        value = first_page.get("value", {})
        total = value.get("total", 0)
        pages = value.get("pages", 0)
        all_items = list(value.get("list", []))

        print(f"[全量获取] 总计 {total} 期 / {pages} 页，"
              f"第1页已获取({len(all_items)}条)")

        if pages <= 1:
            return [self._parse_item(it) for it in all_items if self._parse_item(it)]

        # 翻页获取剩余数据
        for page in range(2, pages + 1):
            time.sleep(self.delay)

            try:
                data = self._request_page(
                    page_no=page,
                    page_size=self.PAGE_SIZE,
                )
                items = data.get("value", {}).get("list", [])
                all_items.extend(items)
            except Exception as e:
                print(f"  [警告] 第{page}页获取失败: {e}，跳过")
                continue

            # 进度提示
            done = len(all_items)
            if page % 10 == 0 or page == pages:
                print(f"  已完成 {page}/{pages} 页 ({done}/{total}条)")

        # 转换为标准格式
        results = []
        for it in all_items:
            record = self._parse_item(it)
            if record:
                results.append(record)

        print(f"[全量获取] 完成！共获取 {len(results)} 期 "
              f"(范围: {results[0]['issue']} ~ {results[-1]['issue']})")
        return results

    # ─────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────

    def _request_page(self, page_no: int = 1, page_size: int = 30) -> Dict:
        """请求一页数据，返回JSON"""
        params = {
            "gameNo": self.GAME_NO,
            "provinceId": "0",
            "pageSize": str(page_size),
            "isVerify": "1",
            "pageNo": str(page_no),
        }
        resp = self.session.get(
            self.API_URL,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_item(item: Dict) -> Optional[Dict]:
        """
        将API返回的单条记录转换为标准格式
        API字段说明：
          lotteryDrawNum     -> 期号，如 "26067"
          lotteryDrawResult  -> 开奖结果字符串，如 "06 16 18 19 28 07 11"
                                前5个是前区(01-35)，后2个是后区(01-12)
          lotteryDrawTime    -> 开奖日期，如 "2026-06-17"
        """
        raw_result = item.get("lotteryDrawResult", "")
        if not raw_result:
            return None

        nums = raw_result.strip().split()
        if len(nums) != 7:
            return None

        try:
            front = sorted(int(n) for n in nums[:5])
            back = sorted(int(n) for n in nums[5:7])
        except ValueError:
            return None

        # 基本合法性校验
        if not (all(1 <= x <= 35 for x in front)
                and all(1 <= x <= 12 for x in back)):
            return None

        issue_num = item.get("lotteryDrawNum", "")

        return {
            "issue": issue_num,
            "draw_date": item.get("lotteryDrawTime", ""),
            "front": front,
            "back": back,
        }

    # ─────────────────────────────────────────
    # 本地种子数据（保留兼容）
    # ─────────────────────────────────────────

    def load_local_seed(self, filepath: str) -> List[Dict]:
        """从本地JSON文件加载种子数据"""
        import json
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
