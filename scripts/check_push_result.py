"""
检查推送结果脚本 - 读取 push_result.json + predict_diagnostic.json
失败时 exit(1) 让 GitHub Actions 步骤变红
"""
import json
import os
import sys

print('═' * 45)
print('  推送结果最终检查 + 诊断信息')
print('═' * 45)

# 显示诊断文件
if os.path.exists('predict_diagnostic.json'):
    print()
    print('📋 predict_diagnostic.json:')
    try:
        with open('predict_diagnostic.json') as f:
            d = json.load(f)
        for k, v in d.items():
            if not k.startswith('_'):
                print(f'  {k}: {v}')
    except Exception as e:
        print(f'  读取失败: {e}')
else:
    print()
    print('  ⚠️ predict_diagnostic.json 不存在')

# 显示推送结果
if os.path.exists('push_result.json'):
    print()
    print('📋 push_result.json:')
    try:
        with open('push_result.json') as f:
            r = json.load(f)
        status = r.get('status', 'unknown')
        icons = {'success': '✅', 'failed': '❌'}
        print(f'  状态: {icons.get(status, "⚠️")} {status}')
        print(f'  期号: {r.get("issue", "?")}')
        if r.get('reason'):
            print(f'  原因: {r["reason"]}')
        if r.get('error_type'):
            print(f'  异常: {r["error_type"]}')
        if r.get('error_detail'):
            print(f'  详情: {str(r["error_detail"])[:200]}')
        if r.get('api_response'):
            print(f'  API响应: {r["api_response"]}')

        if status not in ('success', 'skipped'):
            print()
            print('  ⛔ 推送未成功！此步骤以失败状态退出')
            print()
            print('═' * 45)
            sys.exit(1)
        elif status == 'skipped':
            print()
            print(f'  ℹ️ 推送已跳过（原因: {r.get("reason", "未知")}）')
        else:
            print()
            print('  🎉 推送成功！')
    except Exception as e:
        print(f'  读取 push_result.json 失败: {e}')
        print()
        print('═' * 45)
        sys.exit(1)
else:
    print()
    print('  ⚠️ push_result.json 不存在 → 推送代码未执行')
    print()
    print('  可能原因:')
    print('  1. draws_count < 10 → cmd_predict 提前退出')
    print('  2. 运行中发生未捕获异常')
    print('  3. 指定了 --no-push')
    print()
    print('  请查看上方 predict_diagnostic.json 确认执行断点')
    print()
    print('═' * 45)
    # push_result.json 不存在 = 推送未执行，应视为失败
    sys.exit(1)

print()
print('═' * 45)
