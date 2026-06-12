import os
import json
import urllib.request
import urllib.error

SERVER_URL = os.environ.get('AI_LOG_SERVER')
API_KEY = os.environ.get('AI_LOG_API_KEY')

print('SERVER_URL=', SERVER_URL)
print('API_KEY=', API_KEY[:8] + '...' if API_KEY else None)

if not SERVER_URL:
    print('No SERVER_URL configured; aborting')
    raise SystemExit(1)

payload = json.dumps({'test': 'ping'}).encode('utf-8')
headers = {'Content-Type': 'application/json'}
if API_KEY:
    headers['Authorization'] = f'Bearer {API_KEY}'

req = urllib.request.Request(SERVER_URL, data=payload, headers=headers, method='POST')
print('Sending POST with headers:', headers)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode('utf-8', errors='replace')
        print('Status:', resp.status)
        print('Response:', body)
except urllib.error.HTTPError as e:
    try:
        body = e.read().decode('utf-8', errors='replace')
    except Exception:
        body = '<no body>'
    print('HTTPError:', e.code)
    print('Response body:', body)
except Exception as e:
    print('Request failed:', e)
