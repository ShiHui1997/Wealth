"""
PushPlus 推送模块
文档: http://www.pushplus.plus/doc/
使用 urllib（Python标准库）避免Actions环境依赖问题
"""
import json
import urllib.request
import ssl


class PushPlusNotifier:
    """PushPlus 消息推送器"""

    def __init__(self, token: str, api_url: str = "https://www.pushplus.plus/send"):
        self.token = token
        self.api_url = api_url

    def send(self, title: str, content: str, content_type: str = "html") -> bool:
        """
        发送推送消息
        content_type: "html" 或 "text"
        """
        if not self.token:
            print("[推送] 未配置 PushPlus token，跳过推送")
            return False

        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "template": content_type,  # html 或 text
        }

        # 详细调试日志
        print(f"[推送] API URL: {self.api_url}")
        print(f"[推送] 标题: {title}")
        print(f"[推送] 内容长度: {len(content)} 字符")

        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method='POST'
            )
            # 使用HTTPS + 较长超时（GitHub Actions在美国，到国内API延迟较高）
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, timeout=30, context=ctx)
            body = resp.read().decode('utf-8')
            result = json.loads(body)

            print(f"[推送] API响应: {result}")

            if result.get("code") == 200:
                print(f"[推送] ✅ 发送成功: {result.get('msg', '')}")
                return True
            else:
                print(f"[推送] ❌ 发送失败: {result}")
                return False
        except Exception as e:
            print(f"[推送] ❌❌ 请求异常: {type(e).__name__}: {e}")
            return False

    def send_prediction(self, prediction: str, issue: str = "") -> bool:
        """发送预测结果（专用格式）"""
        title = f"🎯 大乐透预测 {issue}" if issue else "🎯 大乐透预测"
        return self.send(title, prediction, content_type="html")

    def send_text(self, title: str, content: str) -> bool:
        """发送纯文本消息"""
        return self.send(title, content, content_type="text")
