"""
PushPlus 推送模块
文档: http://www.pushplus.plus/doc/
"""
import requests
import json
from typing import Optional


class PushPlusNotifier:
    """PushPlus 消息推送器"""

    def __init__(self, token: str, api_url: str = "http://www.pushplus.plus/send"):
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

        try:
            resp = requests.post(
                self.api_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10
            )
            result = resp.json()
            if result.get("code") == 200:
                print(f"[推送] 发送成功: {result.get('msg', '')}")
                return True
            else:
                print(f"[推送] 发送失败: {result}")
                return False
        except Exception as e:
            print(f"[推送] 请求异常: {e}")
            return False

    def send_prediction(self, prediction: str, issue: str = "") -> bool:
        """发送预测结果（专用格式）"""
        title = f"🎯 大乐透预测 {issue}" if issue else "🎯 大乐透预测"
        return self.send(title, prediction, content_type="html")

    def send_text(self, title: str, content: str) -> bool:
        """发送纯文本消息"""
        return self.send(title, content, content_type="text")
