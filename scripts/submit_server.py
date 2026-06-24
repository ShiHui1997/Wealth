#!/usr/bin/env python3
"""
本地开奖数据提交服务
启动后，手机/电脑在同局域网访问 http://<电脑IP>:7788 即可提交开奖数据，直接写入本地DB。

用法:
  python scripts/submit_server.py              # 默认 0.0.0.0:7788
  python scripts/submit_server.py --port 9000  # 自定义端口
  python scripts/submit_server.py --no-browser # 不自动打开浏览器
"""
import sys
import os
import json
import argparse
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.storage import LotteryStorage
from main import load_config


def get_local_ip():
    """获取本机局域网 IP"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class SubmitHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 自定义日志格式
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def _set_headers(self, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b"{}"

    def do_OPTIONS(self):
        self._set_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/submit.html":
            # 返回提交页面
            html_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "web", "submit_local.html"
            )
            if os.path.exists(html_path):
                with open(html_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self._set_headers("text/html; charset=utf-8")
                self.wfile.write(content.encode("utf-8"))
            else:
                self._set_headers("text/plain", 404)
                self.wfile.write(b"submit_local.html not found")
        else:
            self._set_headers("text/plain", 404)
            self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/submit":
            self._handle_submit()
        else:
            self._set_headers("text/plain", 404)
            self.wfile.write(b"Not Found")

    def _handle_submit(self):
        try:
            body = self._read_body()
            data = json.loads(body)
            issue = data.get("issue", "").strip()
            front = data.get("front", [])
            back = data.get("back", [])

            # 校验
            if not issue:
                raise ValueError("期号不能为空")
            if len(front) != 5 or len(back) != 2:
                raise ValueError("前区需要5个号码，后区需要2个号码")
            for n in front + back:
                if not isinstance(n, int) or n < 1:
                    raise ValueError("号码必须是正整数")

            # 加载配置和DB
            config = load_config()
            storage = LotteryStorage(config["database"]["path"])

            # 检查是否已存在
            existing = storage.get_all_draws()
            existing_issues = {d["issue"] for d in existing}
            if issue in existing_issues:
                self._set_headers()
                self.wfile.write(json.dumps({
                    "ok": False,
                    "error": f"期号 {issue} 已存在，如需更新请联系管理员"
                }, ensure_ascii=False).encode("utf-8"))
                return

            # 写入DB
            today = datetime.now().strftime("%Y-%m-%d")
            front_str = json.dumps(front)
            back_str = json.dumps(back)
            storage.save_draw(issue, today, front_str, back_str)
            print(f"[提交] ✅ 期号 {issue} 写入成功: 前区{front} 后区{back}")

            self._set_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "message": f"期号 {issue} 提交成功！前区 {front} 后区 {back}"
            }, ensure_ascii=False).encode("utf-8"))

        except Exception as e:
            print(f"[提交] ❌ 错误: {e}")
            self._set_headers(status=400)
            self.wfile.write(json.dumps({
                "ok": False,
                "error": str(e)
            }, ensure_ascii=False).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="大乐透开奖数据本地提交服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7788, help="监听端口 (默认 7788)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    local_ip = get_local_ip()
    server = HTTPServer((args.host, args.port), SubmitHandler)

    print("=" * 60)
    print("  大乐透开奖数据提交服务")
    print("=" * 60)
    print(f"  本机访问:   http://localhost:{args.port}")
    print(f"  局域网访问: http://{local_ip}:{args.port}")
    print(f"  监听地址:   {args.host}:{args.port}")
    print("=" * 60)
    print("  按 Ctrl+C 停止服务")
    print()

    if not args.no_browser:
        import webbrowser
        try:
            webbrowser.open(f"http://localhost:{args.port}")
            print(f"[自动] 已打开浏览器")
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[服务] 已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
