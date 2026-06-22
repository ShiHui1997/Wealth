"""
将 PUSHPLUS_TOKEN 环境变量写入 config.yaml
用法: python write_token.py <token>
从 GitHub Actions 调用，避免 YAML 中的引号嵌套问题
"""
import sys
import yaml
import os


def main():
    token = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg_path = "config/config.yaml"

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    cfg["pushplus"]["token"] = token

    with open(cfg_path, "w") as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)

    print(f"PushPlus token 已写入配置 (长度: {len(token)})")
    if not token:
        print("⚠️ WARNING: PUSHPLUS_TOKEN 为空!")
        sys.exit(1)


if __name__ == "__main__":
    main()
