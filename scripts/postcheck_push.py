"""
后置推送验证脚本 - 主运行后发送确认消息
"""
import json
import urllib.request
import ssl
import os
import sys
import datetime

print('═' * 45)
print('  后置推送验证')
print('═' * 45)

# 显示 push_result.json
if os.path.exists('push_result.json'):
    try:
        with open('push_result.json') as f:
            r = json.load(f)
        print(f'push_result.json: status={r.get("status")} issue={r.get("issue")} reason={r.get("reason","")}')
    except Exception as e:
        print(f'读取 push_result.json 失败: {e}')
else:
    print('⚠️ push_result.json 不存在')

try:
    import yaml
    with open('config/config.yaml', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    token = cfg.get('pushplus', {}).get('token', '')
except Exception as e:
    print(f'读取config失败: {e}')
    token = ''

if not token:
    print('[后置] Token为空，跳过后置验证')
    print('═' * 45)
    sys.exit(0)

bj = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
ts = bj.strftime('%m/%d %H:%M')
rid = os.environ.get('GITHUB_RUN_ID', '?')

content = f'<p><b>Actions运行完成</b></p><p>Run #{rid} | {ts} 北京时间</p>'

payload = {
    'token': token,
    'title': f'✅ 后置验证 {ts} #{rid}',
    'content': content,
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
        print(f'[后置] ✅ 发送成功')
    elif code == 903:
        print(f'[后置] ❌ Token无效(code=903): {body.get("msg", "")}')
    else:
        print(f'[后置] ⚠️ API返回(code={code}): {body}')

except Exception as e:
    print(f'[后置] 请求异常: {type(e).__name__}: {e}')

print('═' * 45)
