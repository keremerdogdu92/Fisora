import json
with open('private_samples/real_pilot/benchmark_runs/20260721T115554Z/ai_tie_breaker/firma-1/local-review-data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

targets = [
    '30007700894_EFR2026000010819.pdf',
    '3251298238_EFA2026000000672.pdf',
    '4810577635_AS02026000752460.pdf'
]

for row in data['invoiceRows']:
    if row['fileName'] in targets:
        print(f"=== FILE: {row['fileName']} ===")
        print(f"Research Requested: {row.get('aiResearchRequested')}")
        print(f"Research Query: {row.get('aiResearchQuery')}")
        print(f"Research Profile Keys: {list(row.get('researchProfile', {}).keys()) if row.get('researchProfile') else None}")
        print(f"Semantic Attempts Count: {len(row.get('semanticAttempts', []))}")
        for idx, att in enumerate(row.get('semanticAttempts', [])):
             print(f"  Attempt {idx}: Account={att.get('account_code')} Category={att.get('product_category')} Confidence={att.get('confidence')}")
        print("\n")
