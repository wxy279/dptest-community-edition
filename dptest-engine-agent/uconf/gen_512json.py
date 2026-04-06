import json
import random
import string
import os

def random_string(size):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=size))

# 构造日志数组
logs = []
entry_size = 1000  # 每条日志大约1KB
target_size_kb = 68 # if we set to 512 we can generate totoal 508K data
num_entries = target_size_kb

for i in range(num_entries):
    log_entry = {
        "level": random.choice(["INFO", "WARN", "ERROR"]),
        "message": random.choice(["User login", "File uploaded", "Timeout", "Access denied"]),
        "user_id": random.randint(1000, 9999),
        "ip": f"192.168.{random.randint(0,255)}.{random.randint(0,255)}",
        "details": random_string(entry_size - 100)
    }
    logs.append(log_entry)

# 构造完整 JSON 对象
payload = {
    "service": "my-api",
    "timestamp": "2025-05-06T12:00:00Z",
    "logs": logs
}

# 写入文件（紧凑格式避免空格）
with open("response_512k.json", "w") as f:
    json.dump(payload, f, separators=(",", ":"))

# 从文件中读取
with open("response_512k.json", "r") as f:
    data = json.load(f)

# 打印所有（美化格式）
#print(json.dumps(data, indent=2))
print(json.dumps(data["logs"][:5], indent=2))  # 仅打印前5条日志

#打印文件大小
print(f"File size: {os.path.getsize('response_512k.json') / 1024:.2f} KB")
