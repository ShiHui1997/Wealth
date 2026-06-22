"""
关闭 Issue 并评论处理结果
从 GitHub Actions 调用，通过环境变量接收 Token 和 Issue 编号
"""
import json
import os
import sys
import urllib.request


def github_api(method, url, token, data=None):
    """调用 GitHub API"""
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[GitHub API] 请求失败: {e}")
        return None


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    issue_num = os.environ.get("ISSUE_NUM", "")
    repo = "ShiHui1997/Wealth"

    if not token or not issue_num:
        print(f"[关闭Issue] 缺少参数: token={'有' if token else '无'}, issue={issue_num}")
        return

    # 检查是否有提交数据需要处理
    try:
        with open("submission_result.json") as f:
            result = json.load(f)
        if result.get("skipped"):
            print("[关闭Issue] 手动触发模式，跳过关闭 Issue")
            return
    except FileNotFoundError:
        pass

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    comment_body = (
        "## ✅ 开奖数据已处理完成\n\n"
        "- 📊 **数据库已更新**\n"
        "- 🔮 **已重新生成预测**\n"
        "- 📱 **推送已发送至微信**\n"
        "- 📋 **Walk-Forward回测已执行**\n\n"
        "---\n\n"
        f"*由 GitHub Actions 自动处理 · {now}*"
    )

    # 发表评论
    comment_url = f"https://api.github.com/repos/{repo}/issues/{issue_num}/comments"
    result = github_api("POST", comment_url, token, {"body": comment_body})
    if result:
        print(f"[关闭Issue] 评论已发表 (#{issue_num})")

    # 关闭 Issue
    close_url = f"https://api.github.com/repos/{repo}/issues/{issue_num}"
    result = github_api("PATCH", close_url, token, {"state": "closed"})
    if result:
        print(f"[关闭Issue] Issue #{issue_num} 已关闭")


if __name__ == "__main__":
    main()
