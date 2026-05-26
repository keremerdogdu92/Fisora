from fastapi import APIRouter

from app.domain.journal_entries import build_sample_entries

router = APIRouter()


@router.get("/summary")
def summary() -> dict[str, object]:
    entries = build_sample_entries()
    return {
        "phase": "0",
        "goal": "Validate chart account import, balanced journal entries, and Zirve export candidates.",
        "sample_entry_count": len(entries),
        "sample_entries_balanced": all(entry.is_balanced for entry in entries),
        "risk_flags": sorted({flag for entry in entries for flag in entry.risk_flags}),
    }

