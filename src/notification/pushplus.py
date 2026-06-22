"""
PushPlus 推送模块
文档: http://www.pushplus.plus/doc/
使用 urllib（Python标准库）避免Actions环境依赖问题

推送失败时抛出 PushPlusError 异常（不再静默返回False）
调用方需显式处理异常
"""
import json
import urllib.request
import ssl


class PushPlusError(Exception):
    """推送失败时抛出的异常"""
    def __init__(self, reason: str, api_response: dict = None):
        self.reason = reason
        self.api_response = api_response or {}
        super().__init__(f"PushPlus推送失败: {reason}")


class PushPlusNotifier:
    """PushPlus 消息推送器"""

    def __init__(self, token: str, api_url: str = "https://www.pushplus.plus/send"):
        self.token = token
        self.api_url = api_url

    def send(self, title: str, content: str, content_type: str = "html") -> bool:
        """
        发送推送消息
        content_type: "html" 或 "text"
        成功返回 True
        失败抛出 PushPlusError 异常（不再静默返回 False）
        """
        if not self.token:
            print("[推送] ❌ 未配置 PushPlus token")
            raise PushPlusError("token_empty")

        # 内容截断保护：PushPlus免费版有内容长度限制
        max_content_len = 8000
        if len(content) > max_content_len:
            print(f"[推送] ⚠️ 内容超长({len(content)}字符)，截断到{max_content_len}字符")
            content = content[:max_content_len-200] + "\n<p>...(内容过长已截断)</p>"

        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "template": content_type,
        }

        # 详细调试日志
        print(f"[推送] 📤 API URL: {self.api_url}")
        print(f"[推送] 📋 标题: {title}")
        print(f"[推送] 📊 内容长度: {len(content)} 字符")
        print(f"[推送] 🔑 Token前6位: {self.token[:6]}..." if len(self.token) >= 6 else f"[推送] 🔑 Token: {self.token}")

        try:
            data = json.dumps(payload).encode('utf-8')
            print(f"[推送] 📦 请求体大小: {len(data)} bytes")

            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method='POST'
            )
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, timeout=30, context=ctx)
            body = resp.read().decode('utf-8')
            result = json.loads(body)

            print(f"[推送] 📥 API响应: code={result.get('code')} msg={result.get('msg', '')}")

            if result.get("code") == 200:
                print(f"[推送] ✅ 发送成功: {result.get('msg', '')}")
                return True
            else:
                error_msg = f"API返回错误: code={result.get('code')} msg={result.get('msg', '')}"
                print(f"[推送] ❌ {error_msg}")
                raise PushPlusError("api_error", result)

        except PushPlusError:
            raise  # 重新抛出自己的异常
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace') if e.fp else ""
            print(f"[推送] ❌❌ HTTP错误: {e.code} {e.reason} body={body[:500]}")
            raise PushPlusError(f"http_{e.code}", {"http_code": e.code, "body": body})
        except urllib.error.URLError as e:
            print(f"[推送] ❌❌ URL错误: {e.reason}")
            raise PushPlusError("url_error", {"reason": str(e.reason)})
        except Exception as e:
            print(f"[推送] ❌❌ 请求异常: {type(e).__name__}: {e}")
            raise PushPlusError(f"exception:{type(e).__name__}")

    def send_prediction(self, prediction: str, issue: str = "") -> bool:
        """发送预测结果（专用格式）"""
        title = f"🎯 大乐透预测 {issue}" if issue else "🎯 大乐透预测"
        return self.send(title, prediction, content_type="html")

    def send_text(self, title: str, content: str) -> bool:
        """发送纯文本消息"""
        return self.send(title, content, content_type="text")
