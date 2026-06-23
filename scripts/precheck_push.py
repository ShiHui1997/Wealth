"""
推送预检脚本 - 发送一条测试消息验证PushPlus链路
非阻塞：任何失败都只打印警告，不 exit(1)
"""
import json
import urllib.request
import ssl
import os
import sys
import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import yaml
    with open('config/config.yaml', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    token = cfg.get('pushplus', {}).get('token', '')
except Exception as e:
    print(f'[预检] ⚠️ 读取config失败: {e}')
    token = ''

print('═' * 45)
print('  推送预检（失败不阻断主流程）')
print('═' * 45)

if not token:
    print('[预检] ⚠️ Token为空，跳过预检')
    sys.exit(0)

# 带时间戳 + Run ID 确保每次内容唯一
bj = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
ts = bj.strftime('%m-%d %H:%M')
rid = os.environ.get('GITHUB_RUN_ID', '?')

payload = {
    'token': token,
    'title': f'🔧 预检 {ts} #{rid}',
    'content': f'<p>预检通过 | Run #{rid} | {ts}</p>',
    'template': 'html',
}

try:
    data = json.dumps(payload).encode('utf-8')
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        'https://www.pushplus.plus/send',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    body = json.loads(resp.read().decode('utf-8'))
    code = body.get('code', -1)

    if code == 200:
        print(f'[预检] ✅ 成功: {body.get("msg", "")}')
    elif code == 903:
        print(f'[预检] ❌ Token无效(code=903): {body.get("msg", "")}')
        print('[预检] ⚠️ 请检查 GitHub Secrets 中 PUSHPLUS_TOKEN 是否正确!')
        print('[预检] ⚠️ 获取正确Token: http://www.pushplus.plus/ → 个人中心 → token')
        print('[预检] ⚠️ 不阻断主流程，主运行将继续执行...')
    elif code == 999:
        print(f'[预检] ⚠️ 反垃圾拦截(code=999)，不阻断主流程')
    else:
        print(f'[预检] ⚠️ API返回异常(code={code}): {body}，不阻断主流程')

except Exception as e:
    print(f'[预检] ⚠️ 请求异常: {type(e).__name__}: {e}，不阻断主流程')

print('═' * 45)
