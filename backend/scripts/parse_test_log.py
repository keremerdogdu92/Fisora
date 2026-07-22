from pathlib import Path
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\kerem\.gemini\antigravity\brain\5925a789-b6a2-477a-8aa2-083853ce61c8\.system_generated\tasks\task-533.log")
if not log_path.exists():
    print("Log file not found!")
    exit(1)

content = log_path.read_text(encoding="utf-8")
blocks = content.split("==========================================")

for block in blocks:
    block = block.strip()
    if not block or "File Reference:" not in block:
        continue
    
    ref = re.search(r"File Reference:\s*(\S+)", block)
    category = re.search(r"Product Category:\s*([^\n|]+)", block)
    suggested = re.search(r"AI Suggested Account:\s*([^\n]+)", block)
    research_req = re.search(r"Research Requested:\s*([^\n]+)", block)
    research_query = re.search(r"Research Query:\s*([^\n]+)", block)
    research_evidence = re.findall(r"-\s*Source:\s*([^\n]+)", block)
    accepted = re.search(r"Accepted Account Code:\s*([^\n]+)", block)
    
    print(f"\nRef: {ref.group(1) if ref else 'N/A'}")
    print(f"  Category: {category.group(1).strip() if category else 'N/A'}")
    print(f"  Suggested Account: {suggested.group(1).strip() if suggested else 'N/A'}")
    print(f"  Accepted Account: {accepted.group(1).strip() if accepted else 'N/A'}")
    print(f"  Research Requested: {research_req.group(1).strip() if research_req else 'N/A'}")
    if research_req and research_req.group(1).strip() == "True":
         print(f"  Research Query: {research_query.group(1).strip() if research_query else 'N/A'}")
         print(f"  Evidence Count: {len(research_evidence)}")
         for ev in research_evidence[:3]:
              print(f"    * {ev}")
