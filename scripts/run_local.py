"""
本地运行预测并推送（WorkBuddy 自动化任务调用入口）

用法:
  python scripts/run_local.py          # 完整运行（自动配置提交链接）
  python scripts/run_local.py --no-submit-link   # 不附加提交链接

流程:
 1. 确认数据库就绪（首次自动从种子加载）
 2. 写入 PushPlus Token（从环境变量或 config 读取）
 3. 自动获取本机局域网IP，写入提交链接到 config（让用户手机可访问）
 4. 运行 main.py run（验证 + 校准 + 预测 + 推送）
"""
import sys
import os
import json
import socket
import subprocess
import argparse
import yaml

# 项目根目录
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe")

# 回退到系统 Python
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable


def get_local_ip() -> str:
    """获取本机局域网 IP（用于手机访问提交页面）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # 兜底：枚举网卡
        try:
            hostname = socket.gethostname()
            addrs = socket.getaddrinfo(hostname, None)
            for family, _, _, _, addr in addrs:
                if family == socket.AF_INET:
                    ip = addr[0]
                    if not ip.startswith("127."):
                        return ip
        except Exception:
            pass
        return "localhost"


def write_submit_url_to_config(cfg_path: str, url: str):
    """把提交页面 URL 写入 config.yaml"""
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if "submit" not in cfg or not isinstance(cfg["submit"], dict):
        cfg["submit"] = {}
    cfg["submit"]["url"] = url
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    print(f"[本地运行] ✅ 提交链接已写入 config: {url}")


def run_cmd(cmd: str, cwd: str = PROJECT_DIR):
    """运行命令并实时输出"""
    print(f"\n{'='*50}")
    print(f"[本地运行] 执行: {cmd}")
    print(f"{'='*50}")
    result = subprocess.run(
        cmd, shell=True, cwd=cwd
    )
    if result.returncode != 0:
        print(f"\n[本地运行] ❌ 命令失败 (exit={result.returncode}): {cmd}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="本地运行大乐透预测")
    parser.add_argument("--no-submit-link", action="store_true",
                        help="不在推送中附加开奖数据提交链接")
    args = parser.parse_args()

    os.chdir(PROJECT_DIR)

    # Step 1: 确认数据库就绪
    db_path = os.path.join(PROJECT_DIR, "data", "daletou.db")
    if not os.path.exists(db_path) or os.path.getsize(db_path) < 10000:
        print("[本地运行] 数据库不存在或过小，从种子加载...")
        run_cmd(f'"{VENV_PYTHON}" main.py init')
        run_cmd(f'"{VENV_PYTHON}" main.py load-seed')

    # Step 2: 写入 PushPlus Token
    token = os.environ.get("PUSHPLUS_TOKEN", "")

    # 如果环境变量没有，尝试从 config 读取
    if not token:
        cfg_path = os.path.join(PROJECT_DIR, "config", "config.yaml")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        token = cfg.get("pushplus", {}).get("token", "")

    # 检查 token 是否有效（不是占位符）
    placeholder_tokens = {"", "test_token_from_env_12345", "test_t"}
    if token in placeholder_tokens or token.startswith("test_t"):
        print("\n[本地运行] ❌ PushPlus Token 无效！")
        print("  当前 token:", repr(token[:20]) if token else "(空)")
        print("  请通过以下方式之一设置有效 token:")
        print("    1. 环境变量: set PUSHPLUS_TOKEN=你的真实token")
        print("    2. 直接修改 config/config.yaml 中的 pushplus.token")
        print("    3. 运行: python scripts/write_token.py 你的真实token")
        sys.exit(1)

    # 写入 token 到 config（确保 config 中是真实 token）
    run_cmd(f'"{VENV_PYTHON}" scripts/write_token.py "{token}"')

    # Step 3: 自动获取本机 IP，写入提交链接到 config
    if not args.no_submit_link:
        local_ip = get_local_ip()
        submit_port = 7788
        submit_url = f"http://{local_ip}:{submit_port}/submit"
        cfg_path = os.path.join(PROJECT_DIR, "config", "config.yaml")
        write_submit_url_to_config(cfg_path, submit_url)
        print(f"[本地运行] 📡 本机局域网 IP: {local_ip}")
        print(f"[本地运行] 📝 提交页面: {submit_url}")
        print(f"[本地运行] 💡 提示: 请确保 submit_server.py 已启动，且手机与电脑在同一 Wi-Fi")

    # Step 4: 运行完整预测流程
    print("\n[本地运行] 开始完整运行（验证 + 校准 + 预测 + 推送）...")
    run_cmd(f'"{VENV_PYTHON}" main.py run')

    print("\n[本地运行] ✅ 全部完成！")


if __name__ == "__main__":
    main()
