---
name: systematic-debugging
description: Find root cause before proposing fixes. Verify with user after every fix. No exceptions.
---

# Systematic Debugging

## Iron Law

```text
NO FIXES WITHOUT ROOT CAUSE FIRST
```

Random fixes waste time. Quick patches mask issues.

**Find root cause, then fix. Verify with user after EVERY fix. No exceptions.**

## Four Phases (Must Complete in Order)

### Phase 1: Root Cause Investigation

**BEFORE proposing ANY fix:**

1. **Read error messages completely**
   - Don't skip, they contain the solution
   - Full stack trace, line numbers, error codes

2. **Reproduce consistently**
   - Exact steps to trigger
   - Every time or intermittent?
   - If not reproducible → gather more data

3. **Check recent changes**
   - `git diff`, recent commits
   - Dependencies, config changes
   - Environment differences

4. **Multi-component systems: Add diagnostics**

   When system has layers (CI → build → signing, API → service → DB):

   **Add logging at EACH boundary FIRST, then analyze:**
   ```bash
   # Layer 1: Input
   echo "=== Request: $REQUEST_ID ==="
   echo "Input data: $DATA"

   # Layer 2: Processing
   echo "=== Processing started ==="
   result=$(process_data "$DATA")
   echo "Result: $result"

   # Layer 3: Output
   echo "=== Final output ==="
   echo "$result"
   ```

   Run ONCE to see WHERE it breaks, THEN investigate that layer.

5. **Trace data flow backward**

   Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up to source
   - Fix at source, not symptom

### Phase 2: Pattern Analysis

**Find the pattern:**

1. **Find working similar code**
   - What works that's similar?
   - Compare working vs broken

2. **Compare against reference**
   - If implementing pattern, read reference COMPLETELY
   - Don't skim - every line
   - Understand fully before applying

3. **Identify ALL differences**
   - List every difference, however small
   - Don't assume "that can't matter"

4. **Understand dependencies**
   - What does this need? (settings, config, env)
   - What assumptions does it make?

### Phase 3: Hypothesis

**Scientific method:**

1. **Form single hypothesis**
   - "I think X is root cause because Y"
   - Be specific

2. **Test minimally**
   - SMALLEST possible change
   - One variable at a time
   - Don't fix multiple things

3. **Verify**
   - Worked? → Phase 4
   - Didn't work? → NEW hypothesis
   - Don't stack fixes

4. **When you don't know**
   - Say "I don't understand X"
   - Don't pretend
   - Ask for help or research

### Phase 4: Implementation & Verification

**Fix root cause, verify with user:**

1. **Create failing test** (use `test-driven-development` skill)

2. **Implement single fix** (address root cause identified in Phase 1-3)

3. **Run tests, report results**

4. **ASK USER TO VERIFY (MANDATORY):**

   **Don't assume "tests pass" = "problem solved"**

   > "Tests pass ✅
   >
   > Ama bu senin için çözüldü anlamına gelmeyebilir.
   >
   > Şunu kontrol eder misin:
   > [Specific thing to check - exact steps, not vague]
   >
   > Çözüldü mü?"

   **Wait for user response.**

   - User says "Evet çözüldü": ✅ Done
   - User says "Hayır": → Progressive detail levels (below)

## Progressive Detail Levels (Attempt Counter)

Track failed attempts. Increase detail each time.

### Attempt 1 Failed

User says "çözülmedi" after first fix.

**Response:**

> "Anlıyorum, çözülmedi.
>
> Şu anda tam olarak ne oluyor?
> Ne bekliyordun?"

**Get brief clarification:**
- What's actually happening now
- What should be happening
- Any error messages or unexpected behavior

**Then:** Return to Phase 1 with new information.

**Counter: 1**

---

### Attempt 2 Failed

User says "çözülmedi" after second fix.

**Response:**

> "İkinci deneme de olmadı. Daha detaylı konuşalım.
>
> **Şu anki süreç:**
>
> 1. [User/system does X]
> 2. [Component A processes it]
> 3. [Component B does Y]
> 4. [Result: Z happens]
>
> **Benim 'çözüldü' anlayışım:**
>
> - Test A passes ✅
> - Test B passes ✅
> - [Behavior X] happens
>
> **Senin 'çözüldü' kriteri ne?**
>
> Ne olursa 'evet çözüldü' diyeceksin?
>
> Mümkünse örnek ver: 'X yapınca Y olmalı, şu an Z oluyor'"

**Get deeper clarification:**
- User's exact acceptance criteria
- Example scenario (input → expected output)
- What's the gap between expected and actual

**Then:** Return to Phase 1 with clearer success criteria.

**Counter: 2**

---

### Attempt 3 Failed

User says "çözülmedi" after third fix.

**STOP. Don't attempt fix #4.**

This is not a simple bug. This is architectural, or we're solving the wrong problem.

**FULL PIPELINE ANALYSIS MODE:**

```text
═══════════════════════════════════════════════════════
FULL DETAY - MASAYA YATIRALIM
═══════════════════════════════════════════════════════

Üç farklı fix denedim, hiçbiri çalışmadı.

Şimdi tüm sistemi masaya yatırıp, gerçekten neyin yanlış
olduğunu bulalım.

───────────────────────────────────────────────────────
1. BU PROBLEMİ ETKİLEYEN TÜM COMPONENTLER
───────────────────────────────────────────────────────

[List EVERYTHING that touches this problem]

Örnek:
1. PDF Input (user uploads)
2. pdfplumber Parse (table extraction)
3. Parse → Structured format conversion
4. AI Prompt construction
5. AI Service call
6. AI Response parsing
7. Validation rules
8. Normalization logic
9. Database persistence
10. Frontend display

───────────────────────────────────────────────────────
2. ŞU ANKİ AKIŞ (ADIM ADIM)
───────────────────────────────────────────────────────

[Show data flow through system with current state]

Örnek:

PDF (input)
  ├─ File size: 2.5MB
  ├─ Pages: 3
  └─ Format: text-based PDF ✓
  ↓
pdfplumber Parse
  ├─ Tables extracted: 2
  ├─ Rows detected: 15
  ├─ Columns detected: 5
  └─ Quality: UNKNOWN ⚠️ (not measured)
  ↓
Structured conversion
  ├─ Format: JSON
  ├─ Fields: 12
  └─ Quality: UNKNOWN ⚠️ (not measured)
  ↓
AI Processing
  ├─ Prompt length: 2,500 tokens
  ├─ Response time: 3.2s
  ├─ Response: Valid JSON ✓
  └─ Quality BEFORE validation: UNKNOWN ⚠️ (not measured)
  ↓
Validation
  ├─ Rules applied: 8
  ├─ Items checked: 15
  ├─ Passed: 4 (27%)
  ├─ Failed: 11 (73%)
  └─ Reject reasons: UNKNOWN ⚠️ (not logged)
  ↓
Final result: 27% accuracy ❌

───────────────────────────────────────────────────────
3. BENİM VARSAYIMLARIM (yanlış olabilir)
───────────────────────────────────────────────────────

[List all assumptions you made]

Örnek:

1. pdfplumber parse "success" = iyi parse edildi
   ▶ Gerçekte: Table structure bozulmuş olabilir
   ▶ Bu doğru mu?

2. AI response validation fail = AI kötü veri üretti
   ▶ Gerçekte: Validation çok sıkı olabilir
   ▶ Bu doğru mu?

3. Validation pass = data kaliteli
   ▶ Gerçekte: Validation sadece format check yapıyor olabilir
   ▶ Bu doğru mu?

4. End-to-end %27 accuracy = AI accuracy %27
   ▶ Gerçekte: AI %99 doğru ama validation %73 reject ediyor olabilir
   ▶ Bu doğru mu?

───────────────────────────────────────────────────────
4. ÖLÇÜLMEYEN NOKTALAR
───────────────────────────────────────────────────────

Şu anki testler sadece end-to-end bakıyor:
✅ PDF in → Final result out

Ama intermediate quality'leri ölçmüyoruz:

❌ pdfplumber parse quality
   - Table structure preservation
   - Row/column accuracy
   - Text extraction quality

❌ AI output quality BEFORE validation
   - Content accuracy (ignoring format)
   - Compare with reference (browser ChatGPT)

❌ Validation rejection analysis
   - Which rules reject most?
   - Are rejections correct? (Is data actually bad?)
   - Format issues vs content issues

❌ Component X output quality
   [Add other unmeasured points]

───────────────────────────────────────────────────────
5. NEREDE BAŞLAYALIM?
───────────────────────────────────────────────────────

[Present investigation options]

**Option A: [Component X] Quality İncele**

Nasıl:
- [Specific approach]
- [What to measure]
- [How to measure]

Effort: [Low/Medium/High] - [time estimate]

Bulacağımız:
- [What we'll learn]
- [What question it answers]

Risk:
- [What could go wrong]
- [What we might miss]

Example:
"10 sample PDF al, pdfplumber output'unu manuel incele,
table structure korunuyor mu ölç"

───────────────────────────────────

**Option B: [Component Y] Quality İncele**

Nasıl:
- [Specific approach]

Effort: [Low/Medium/High] - [time estimate]

Bulacağımız:
- [What we'll learn]

Risk:
- [What could go wrong]

Example:
"Validation'ı bypass et, AI raw output'u al, manuel accuracy ölç,
browser ChatGPT ile compare et"

───────────────────────────────────

**Option C: [Component Z] Audit**

Nasıl:
- [Specific approach]

Effort: [Low/Medium/High] - [time estimate]

Bulacağımız:
- [What we'll learn]

Risk:
- [What could go wrong]

Example:
"Validation rules'ları listele, her rule kaç reject yapıyor say,
rejected samples'ları incele (gerçekten hatalı mı?)"

───────────────────────────────────

**Option D: End-to-End Comparison**

Nasıl:
- [Specific approach]

Effort: [Low/Medium/High] - [time estimate]

Bulacağımız:
- [What we'll learn]

Risk:
- [What could go wrong]

Example:
"Aynı PDF'i browser ChatGPT'ye at vs bizim sisteme at,
intermediate steps'leri compare et, nerede diverge oluyor bul"

───────────────────────────────────────────────────────
6. BENİM ÖNERİM
───────────────────────────────────────────────────────

[State your recommendation and WHY]

Örnek:

Önce Option B (AI Quality Before Validation)

Neden:
- En hızlı (30 dakika)
- Hemen gösterir: AI mi kötü, validation mı sıkı?
- Eğer AI %99 doğruysa → validation problemi
- Eğer AI %30 doğruysa → parse veya prompt problemi
- Diğer seçenekler sonraki adım olur

Sonra bulgulara göre Option A, C veya D'ye geçeriz.

───────────────────────────────────────────────────────
7. SONRAKI ADIM
───────────────────────────────────────────────────────

Nereden başlayalım?

A / B / C / D / [Farklı fikir]

═══════════════════════════════════════════════════════
```

**Wait for user to choose investigation approach.**

**Then:** Execute chosen investigation, report findings, THEN fix based on evidence.

**Counter: 3**

---

## Don't Blame Downstream Components

**Common anti-pattern:**

```text
Component A ✅ (our code, tests pass)
  ↓
Component B ✅ (our code, tests pass)
  ↓
Component C ❌ (external service, "bad output")
  ↓
Conclusion: "Component C sucks" ← WRONG
```

**This is almost always wrong.**

### Why "Blame Downstream" Fails

When end-to-end fails but intermediate tests pass:

**The problem is usually:**
1. We're not measuring intermediate quality correctly
2. Tests check existence, not quality
3. Validation is too strict/loose
4. We're sending bad input to external component

**The problem is rarely:**
- External component suddenly got worse
- External API changed (usually documented)

### Correct Investigation Approach

**Before blaming external component:**

**Measure quality at EVERY step:**

```text
PDF Input
  ├─ Quality: [How to verify input is good]
  ↓
Parse
  ├─ Output quality: [Measure THIS - don't assume "success" = good]
  ↓
External Service Input
  ├─ Input quality: [What are we sending? Is it good?]
  ↓
External Service Output
  ├─ Output quality: [What did it return? Is it good?]
  ↓
Validation
  ├─ Pass/fail rate: [How many pass vs fail?]
  ├─ Rejection reasons: [WHY did it fail?]
  └─ Are rejections correct? [Is data actually bad?]
  ↓
Final result
```

**Then compare:**

- External service received good input, produced good output, but validation rejects → **Validation is problem**
- External service received good input, produced bad output → **External service is problem**
- External service received bad input → **Our parse/preparation is problem**

### Validation Transparency

**When validation rejects data:**

**DON'T just say:**
> "Validation failed ❌"

**DO say:**

> "Validation rejected X out of Y items (Z% reject rate)
>
> **Rejection breakdown:**
>
> - Rule A: 5 rejections
>   Reason: line_item_count_mismatch
>   Example: Expected 4 items, got 3
>
> - Rule B: 3 rejections
>   Reason: decimal_precision_mismatch
>   Example: 1250.0 vs 1250.00
>
> - Rule C: 2 rejections
>   Reason: vat_group_structure_invalid
>   Example: Expected flat list, got nested groups
>
> **Sample rejected item:**
>
> ```json
> {
>   "invoice_id": "FTR123",
>   "line_items": [
>     {"description": "Ürün A", "amount": 100.0},
>     {"description": "Ürün B", "amount": 50.0}
>   ],
>   "total": 150.0
> }
> ```
>
> Rejected by: Rule A (expected 3 items, schema says minimum 3)
>
> **Soru:** Bu rejection doğru mu? Data gerçekten hatalı mı,
> yoksa validation çok sıkı mı?"

**Then inspect rejected samples with user before concluding "AI/parse is bad".**

### The "Browser ChatGPT Works, Our System Doesn't" Problem

**Symptom:**
- Same PDF → browser ChatGPT → %99 accuracy
- Same PDF → our system → %30 accuracy
- Conclusion: "Our system's AI call is broken" ← MAYBE WRONG

**Before blaming AI integration:**

**Measure intermediate quality:**

1. **What are we sending to AI?**
   - Extract the EXACT prompt + data we send
   - Send SAME prompt + data to browser ChatGPT
   - Compare: Same input?

2. **What does AI return?**
   - Extract AI's raw response (before validation)
   - Measure accuracy of raw response (ignore format issues)
   - Compare with browser ChatGPT response

3. **What does validation do?**
   - Pass/fail rate
   - Rejection reasons
   - Are rejections about CONTENT or FORMAT?

**Typical finding:**

```text
AI raw output: %98 accurate (content correct)
After validation: %30 pass rate
Root cause: Validation rejects %68 for FORMAT issues (decimal precision,
            structure differences, field naming)
Solution: Loosen format validation OR tighten AI output format specification
```

**NOT:** "AI integration is broken"

---

## Integration with verification-before-completion

verification-before-completion is always-active. Here's how they work together:

**After implementing fix:**

1. **verification-before-completion runs automatically:**
   - Identifies verification command (pytest, npm test, etc.)
   - Runs command
   - Collects output
   - Checks exit code, counts failures

2. **systematic-debugging uses evidence:**

   > "Tests çalıştırdım:
   >
   > ```
   > $ pytest tests/test_invoice.py -v
   > ======================== 5 passed in 1.2s ========================
   > Exit code: 0
   > ```
   >
   > Evidence: Tests pass ✅
   >
   > Ama bu senin için çözüldü anlamına gelmeyebilir.
   >
   > [Specific thing to check]
   >
   > Çözüldü mü?"

3. **User confirms or denies:**
   - "Evet" → Done ✅
   - "Hayır" → Attempt counter increases, progressive detail

**You don't explicitly invoke verification-before-completion. It runs automatically before you make any claim.**

---

## User Signals → Immediate Action

**These phrases mean STOP EVERYTHING and change approach:**

| User Says | What It Means | Immediate Action |
|-----------|---------------|------------------|
| **"Is that not happening?"** | You assumed without verifying | STOP. Show evidence. Run actual command/check, show output. |
| **"Will it show us...?"** | You should have added diagnostics | STOP. Add logging at every boundary. Run once, show results, THEN analyze. |
| **"Stop guessing"** | Proposing fixes without understanding | STOP. Return to Phase 1. No more fixes until root cause proven. |
| **"This isn't working"** (frustrated) | Not understanding what "working" means | STOP. Ask: "Exactly what should happen? What would make you say 'çözüldü'?" |
| **"Try again"** (repeated) | Stuck in loop | STOP. Count attempts. If 3+, this is architectural. Full pipeline analysis. |
| **"Neden böyle oluyor?"** (repeated) | Fixing symptoms, not cause | STOP. Return to Phase 1. Trace data flow backward to source. |
| **Silence** (user not responding) | Lost them OR frustrated | STOP. Summarize: "Where we are + what I'm trying + what's unclear. Continue or change approach?" |

**When you see ANY of these:**

1. **Stop current approach immediately**

2. **Acknowledge the signal:**

   > "Fark ettim: [Which signal]. [What I did wrong].
   >
   > Yaklaşımı değiştiriyorum."

3. **Change approach based on signal** (see table above)

4. **Get user buy-in before continuing:**

   > "Yeni plan:
   >
   > 1. [What I'll do differently]
   > 2. [What output you'll see]
   > 3. [How we'll know if it worked]
   >
   > Bu yaklaşım mantıklı mı?"

5. **Wait for approval**

### Proactive Checkpoint (Before User Gets Frustrated)

**Don't wait for user to signal frustration.**

**After Attempt 2 fails:**

Proactively checkpoint:

> "İki farklı yaklaşım denedim, ikisi de çalışmadı:
>
> 1. [Attempt 1]: [Ne oldu]
> 2. [Attempt 2]: [Ne oldu]
>
> Şu anki durumu netleştirelim:
>
> - Tam olarak ne çalışmıyor? [Your understanding]
> - Ne olursa 'çözüldü' diyeceksin? [Acceptance criteria]
> - Şu ana kadar ne denedim: [Summary]
>
> Devam etmeden önce: Doğru şeyi mi çözmeye çalışıyorum?"

**Wait for clarification BEFORE Attempt #3.**

---

## Expected Behavior Confirmation

**Before implementing fix for "feature doesn't work" issues:**

> "Fix yapmadan önce expected behavior'ı confirm edelim:
>
> **Scenario:** [User action]
>
> **Expected:**
> - Step 1: [What should happen]
> - Step 2: [What should happen]
> - Final result: [End state]
>
> **Current (broken):**
> - Step 1: [What actually happens]
> - Step 2: [What actually happens]
> - Final result: [End state]
>
> **My fix will:**
> - Change: [What I'm modifying]
> - So that: [New behavior]
>
> Bu beklentini karşılıyor mu?"

**Wait for confirmation.**

**If user says "hayır, öyle değil":**

> "Anladım. Beklentin şu mu: [Try to understand]"

**Iterate until user says "evet, aynen öyle".**

**THEN** implement.

---

## Verification Checklist

Before claiming bug fixed:

- [ ] **Root cause identified** (not symptom)
- [ ] **Created regression test** (RED → GREEN via TDD skill)
- [ ] **Single fix applied** (not multiple changes)
- [ ] **Tests pass**
- [ ] **Asked user "Çözüldü mü?"**
- [ ] **User confirmed "Evet çözüldü"**

Can't check all? Not done yet.

---

## Red Flags (STOP and Follow Process)

- "Quick fix for now"
- "Just try X and see"
- "Add multiple changes"
- "Skip test, manually verify"
- "Probably X, let me fix"
- "Don't fully understand but this might work"
- Proposing solutions before tracing data flow
- **"Tests pass, so it's fixed" (without user confirm)**
- **"One more fix" (when tried 3+ already)**
- **Each fix reveals new problem elsewhere**

**All mean: STOP. Follow process.**

---

## Common Rationalizations (REJECT)

| Excuse | Reality |
|--------|---------|
| "Issue simple, don't need process" | Simple has root cause. Process is fast. |
| "Emergency, no time" | Systematic is FASTER than thrashing. |
| "Just try this first" | First fix sets pattern. Do it right. |
| "Tests pass = fixed" | User defines "fixed", not tests. |
| "Write test after confirming fix" | Untested fixes don't stick. |
| "Multiple fixes save time" | Can't isolate what worked. |
| "Reference too long" | Partial understanding guarantees bugs. |
| "One more fix" (after 3) | 3+ = architectural. Don't guess more. |
| "External component must be bad" | Measure intermediate quality first. |

**All mean: Follow process. No shortcuts.**

---

## Integration with Other Skills

**Use with:**
- `test-driven-development`: Create regression test (Phase 4, Step 1)
- `verification-before-completion`: Final verification before claiming done

**Don't:**
- Skip root cause because "emergency"
- Stack fixes without verification
- Claim fixed without user confirmation
- Blame external components without measuring intermediate quality

---

**End of Systematic Debugging Skill**
