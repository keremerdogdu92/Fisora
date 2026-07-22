from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
log_path = Path(r"C:\Users\kerem\.gemini\antigravity\brain\5925a789-b6a2-477a-8aa2-083853ce61c8\.system_generated\tasks\task-578.log")
content = log_path.read_text(encoding="utf-8")
blocks = content.split("==========================================")

for block in blocks:
    if "4810577635_AS02026000752460" in block:
        print(block)
