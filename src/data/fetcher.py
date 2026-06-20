"""
大乐透历史数据获取模块
支持多数据源，以50期为一批获取历史数据，直到第一期
"""
import requests
import time
import re
import json
import socket
from typing import List, Dict, Optional


class DaletouFetcher:
    """大乐透数据获取器（多数据源容错）"""

    # 常见代理端口列表（按优先级排序）
    PROXY_PORTS = [
        ("http", "127.0.0.1", 1080),     # v2rayN HTTP
        ("http", "127.0.0.1", 10809),    # v2rayN HTTP2
        ("http", "127.0.0.1", 7890),     # Clash
        ("socks5h", "127.0.0.1", 7890),  # Clash SOCKS5
        ("socks5h", "127.0.0.1", 10808), # v2rayN SOCKS
        ("http", "127.0.0.1", 10808),
        ("http", "127.0.0.1", 7897),     # Clash Verge
        ("http", "127.0.0.1", 1087),
    ]

    def __init__(self, batch_size: int = 50, delay: float = 1.0):
        self.batch_size = batch_size
        self.delay = delay
        self.proxies = None

        # 第一步：检测可用代理
        self._detect_proxy()

        # 创建会话
        self.session = requests.Session()
        if self.proxies:
            self.session.proxies.update(self.proxies)
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
        self.fetched_issues = set()

    def _detect_proxy(self):
        """检测本地可用的代理端口"""
        print("[网络] 检测本地代理...")

        for proto, host, port in self.PROXY_PORTS:
            # 先用 socket 快速检测端口是否监听
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.8)
                result = s.connect_ex((host, port))
                s.close()
                if result != 0:
                    continue  # 端口没在监听，跳过
            except Exception:
                continue

            # 端口在监听，再测试能否通过它访问网络
            proxy_url = f"{proto}://{host}:{port}"
            test_proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
            try:
                r = requests.get(
                    "https://www.baidu.com",
                    proxies=test_proxies,
                    timeout=3,
                )
                if r.status_code == 200:
                    self.proxies = test_proxies
                    print(f"[网络] ✓ 使用代理: {proxy_url}")
                    return
            except Exception as e:
                print(f"[网络]   端口 {port} 在线但不可用: {type(e).__name__}")

        print("[网络] 未检测到可用代理，使用直连")

    # ─────────────────────────────────────────
    # 公开方法
    # ─────────────────────────────────────────

    def fetch_latest(self) -> Optional[Dict]:
        """获取最新一期开奖数据（多源依次尝试）"""
        print("[获取最新] 正在获取...")
        sources = [
            ("500彩票网API", self._fetch_from_500_api_latest),
            ("体彩官网",   self._fetch_from_lottery_gov_latest),
            ("500网页面",   self._fetch_from_500_page_latest),
        ]
        for name, fn in sources:
            try:
                result = fn()
                if result:
                    print(f"[获取最新] ✓ 来源: {name} | 期号: {result['issue']}")
                    return result
            except Exception as e:
                print(f"[获取最新] ✗ {name} 失败: {e}")

        print("[获取最新] 所有数据源均失败")
        return None

    def fetch_history_batch(self, batch_num: int) -> List[Dict]:
        """获取一批历史数据"""
        print(f"[批量获取] 第{batch_num}批（每批{self.batch_size}期）...")

        sources = [
            ("500彩票网API", lambda n: self._fetch_from_500_api(n)),
            ("体彩官网",     lambda n: self._fetch_from_lottery_gov(n)),
            ("500网页面",     lambda n: self._fetch_from_500_page(n)),
        ]
        for name, fn in sources:
            try:
                results = fn(batch_num)
                if results:
                    unique = []
                    for r in results:
                        if r["issue"] not in self.fetched_issues:
                            self.fetched_issues.add(r["issue"])
                            unique.append(r)
                    print(f"[批量获取] ✓ 来源: {name} | 获取到 {len(unique)} 条新记录")
                    return unique
            except Exception as e:
                print(f"[批量获取] ✗ {name} 失败: {e}")

        print("[批量获取] 本批所有源均失败")
        return []

    def set_fetched_issues(self, issues: set):
        self.fetched_issues = issues

    # ══════════════════════════════════════════
    # 数据源1：500彩票网隐藏API（首选，返回CSV）
    # ══════════════════════════════════════════

    def _fetch_from_500_api(self, batch_num: int) -> List[Dict]:
        """500彩票网隐藏接口 - 返回CSV格式"""
        results = []
        url = "https://datachart.500.com/dlt/history/newinc/outdata.php"
        params = {
            "start": str((batch_num - 1) * self.batch_size + 1),
            "end": str(batch_num * self.batch_size),
        }

        resp = self._safe_get(url, params=params, timeout=15,
                              encoding="utf-8")
        if not resp or len(resp.strip()) < 20:
            return []

        for line in resp.strip().split("\n"):
            parts = line.split(",")
            if len(parts) < 8:
                continue
            issue = parts[0].strip().replace('"', '')
            if not issue.isdigit() or len(issue) < 6:
                continue

            front = []
            back = []
            for i in range(1, 6):
                if i < len(parts):
                    n = parts[i].strip().replace('"', '')
                    if n.isdigit():
                        num = int(n)
                        if 1 <= num <= 35:
                            front.append(num)
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

        return results

    def _fetch_from_500_api_latest(self) -> Optional[Dict]:
        """从500彩票API获取最新一期"""
        url = "https://datachart.500.com/dlt/history/newinc/outdata.php"
        params = {"start": "1", "end": "1"}

        resp = self._safe_get(url, params=params, timeout=10,
                              encoding="utf-8")
        if not resp:
            return None

        lines = resp.strip().split("\n")
        if not lines:
            return None

        parts = lines[0].split(",")
        if len(parts) >= 8:
            return self._parse_500_line(parts)

        return None

    def _parse_500_line(self, parts):
        """解析500彩票网的一行数据"""
        issue = parts[0].strip().replace('"', '')
        front = sorted([int(p.strip()) for p in parts[1:6]
                        if p.strip().isdigit()])
        back = sorted([int(p.strip()) for p in parts[6:8]
                       if p.strip().isdigit()])
        if issue and len(front) == 5 and len(back) == 2:
            return {"issue": issue, "draw_date": "", "front": front, "back": back}
        return None

    # ══════════════════════════════════════════
    # 数据源2：中国体彩官方网站
    # ══════════════════════════════════════════

    def _fetch_from_lottery_gov(self, batch_num: int) -> List[Dict]:
        """
        中国体彩官网大乐透开奖查询
        URL: https://webapi.sporttery.cn/gateway/jc/getLotteryHistoryInfoV2.qry
        """
        results = []
        url = "https://webapi.sporttery.cn/gateway/jc/getLotteryHistoryInfoV2.qry"
        params = {
            "gameNo": "85",       # 大乐透游戏编号
            "pageSize": str(self.batch_size),
            "pageNo": str(batch_num),
            "isAnalysis": "false",
        }

        resp = self._safe_get(url, params=params, timeout=15,
                              encoding="utf-8")
        if not resp:
            return []

        try:
            data = json.loads(resp)
            items = data.get("value", {}).get("list", [])
        except (json.JSONDecodeError, AttributeError):
            return []

        for item in items:
            issue_str = str(item.get("lotteryDrawNum", "") or item.get("lotteryDrawResult", ""))
            draw_date = item.get("lotteryDrawTime", "")[:10]

            # 解析号码字符串，如 "01 05 12 23 35 | 03 08"
            numbers_raw = item.get("lotteryDrawResult", "")
            front, back = self._parse_numbers_string(numbers_raw)

            if len(front) == 5 and len(back) == 2:
                results.append({
                    "issue": issue_str,
                    "draw_date": draw_date,
                    "front": sorted(front),
                    "back": sorted(back),
                })

        return results

    def _fetch_from_lottery_gov_latest(self) -> Optional[Dict]:
        """从体彩官网获取最新一期"""
        url = "https://webapi.sporttery.cn/gateway/jc/getLotteryHistoryInfoV2.qry"
        params = {
            "gameNo": "85",
            "pageSize": "1",
            "pageNo": "1",
            "isAnalysis": "false",
        }

        resp = self._safe_get(url, params=params, timeout=10,
                              encoding="utf-8")
        if not resp:
            return None

        try:
            data = json.loads(resp)
            items = data.get("value", {}).get("list", [])
            if items:
                item = items[0]
                issue_str = str(item.get("lotteryDrawNum", ""))
                draw_date = item.get("lotteryDrawTime", "")[:10]
                front, back = self._parse_numbers_string(
                    item.get("lotteryDrawResult", ""))
                if len(front) == 5 and len(back) == 2:
                    return {
                        "issue": issue_str,
                        "draw_date": draw_date,
                        "front": sorted(front),
                        "back": sorted(back),
                    }
        except (json.JSONDecodeError, AttributeError):
            pass
        return None

    @staticmethod
    def _parse_numbers_string(s: str):
        """解析号码字符串 '01 05 12 23 35 | 03 08' → ([1,5,12,23,35], [3,8])"""
        front = []
        back = []
        if "|" in s:
            parts_s = s.split("|")
            front_part = parts_s[0].strip()
            back_part = parts_s[1].strip() if len(parts_s) > 1 else ""
        else:
            front_part = s.strip()
            back_part = ""

        for n in front_part.split():
            n = n.strip().lstrip("0") or "0"
            if n.isdigit() and 1 <= int(n) <= 35:
                front.append(int(n))

        for n in back_part.split():
            n = n.strip().lstrip("0") or "0"
            if n.isdigit() and 1 <= int(n) <= 12:
                back.append(int(n))

        return front, back

    # ══════════════════════════════════════════
    # 数据源3：500彩票网页面解析（备用）
    # ══════════════════════════════════════════

    def _fetch_from_500_page(self, batch_num: int) -> List[Dict]:
        """500彩票网页面抓取"""
        results = []
        url = f"https://kaijiang.500.com/dlt.shtml"
        if batch_num > 1:
            url += f"?page={batch_num}"

        resp = self._safe_get(url, timeout=15, encoding="gb2312")
        if not resp:
            return []

        text = resp
        rows = re.findall(
            r'<tr[^>]*class="[^"]*tr[^"]*"[^>]*>.*?</tr>',
            text, re.DOTALL | re.IGNORECASE
        )
        if not rows:
            rows = re.findall(r'<tr[^>]*>.*?</tr>', text, re.DOTALL)

        for row in rows:
            clean_row = row.replace("<br>", "").replace("&nbsp;", " ")

            # 提取期号
            issue_match = re.search(r'(\d{7})\s*期|第\s*(\d{7})', clean_row)
            issue = None
            if issue_match:
                issue = issue_match.group(1) or issue_match.group(2)

            # 提取号码（用 ball_ 类名或直接数字模式）
            nums = [int(n) for n in re.findall(r'>(\d{2})<', row)
                    if n.isdigit()]
            valid_front = [n for n in nums if 1 <= n <= 35]

            if issue and len(valid_front) >= 7:
                front = sorted(valid_front[:5])
                remaining_back = [n for n in valid_front[5:] if 1 <= n <= 12]
                if len(remaining_back) < 2:
                    remaining_back = [n for n in nums if 1 <= n <= 12][:2]
                back = sorted(remaining_back[:2]) if remaining_back else [1, 2]

                if len(front) == 5 and len(back) == 2:
                    results.append({
                        "issue": issue,
                        "draw_date": "",
                        "front": front,
                        "back": back,
                    })

        return results

    def _fetch_from_500_page_latest(self) -> Optional[Dict]:
        """500彩票网页面获取最新一期"""
        resp = self._safe_get(
            "https://kaijiang.500.com/dlt.shtml",
            timeout=10, encoding="gb2312"
        )
        if not resp:
            return None

        text = resp
        nums = [int(n) for n in re.findall(r'>(\d{2})<', text)]
        valid_front = [n for n in nums if 1 <= n <= 35]

        if len(valid_front) < 7:
            return None

        front = sorted(valid_front[:5])
        remaining_back = [n for n in nums[5:12] if 1 <= n <= 12]
        back = sorted(remaining_back[:2])

        issue_match = re.search(r'(\d{7})', text[:3000])
        issue = issue_match.group(1) if issue_match else ""

        if issue and len(back) >= 2:
            return {"issue": issue, "draw_date": "", "front": front, "back": back}
        return None

    # ─────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────

    def _safe_get(self, url: str, params=None, timeout: int = 10,
                  encoding: str = "utf-8") -> Optional[str]:
        """
        安全的GET请求：先尝试带代理，失败后自动降级为直连
        返回响应文本或None
        """
        # 尝试1：用当前配置（可能带代理）
        try:
            r = self.session.get(url, params=params, timeout=timeout)
            r.encoding = encoding
            if r.status_code == 200 and len(r.text.strip()) > 10:
                return r.text
        except requests.exceptions.ProxyError as e:
            print(f"   [代理错误] {url}: {e}")
        except requests.exceptions.ConnectTimeout:
            print(f"   [连接超时] {url}")
        except requests.exceptions.ConnectionError as e:
            print(f"   [连接失败] {url}: {type(e).__name__}")
        except requests.exceptions.RequestException as e:
            print(f"   [请求异常] {url}: {e}")

        # 尝试2：如果之前用了代理且失败了，尝试直连
        if self.session.proxies:
            print(f"   → 降级为直连重试: {url}")
            try:
                r = requests.get(
                    url, params=params, timeout=timeout,
                    headers=self.session.headers.copy(),
                )
                r.encoding = encoding
                if r.status_code == 200 and len(r.text.strip()) > 10:
                    return r.text
            except Exception as e:
                print(f"   [直连也失败] {url}: {e}")

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
