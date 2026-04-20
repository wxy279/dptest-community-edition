import json
import os
import random
import string


def random_string(size):
    return "".join(random.choices(string.ascii_letters + string.digits, k=size))


# Build the log array.
logs = []
entry_size = 1000  # Each log entry is about 1 KB.
target_size_kb = 68  # If set to 512, the generated file is about 508 KB.
num_entries = target_size_kb

for i in range(num_entries):
    log_entry = {
        "level": random.choice(["INFO", "WARN", "ERROR"]),
        "message": random.choice(["User login", "File uploaded", "Timeout", "Access denied"]),
        "user_id": random.randint(1000, 9999),
        "ip": f"192.168.{random.randint(0,255)}.{random.randint(0,255)}",
        "details": random_string(entry_size - 100),
    }
    logs.append(log_entry)

# Build the full JSON payload.
payload = {
    "service": "my-api",
    "timestamp": "2025-05-06T12:00:00Z",
    "logs": logs,
}

# Write the file in compact JSON form to avoid extra spaces.
with open("response_512k.json", "w") as f:
    json.dump(payload, f, separators=(",", ":"))

# Read the file back.
with open("response_512k.json", "r") as f:
    data = json.load(f)

# Print the full payload in pretty JSON if needed.
# print(json.dumps(data, indent=2))
print(json.dumps(data["logs"][:5], indent=2))  # Print only the first 5 log entries.
# Print the generated file size.
print(f"File size: {os.path.getsize('response_512k.json') / 1024:.2f} KB")
