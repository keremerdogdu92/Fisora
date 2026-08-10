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
   - Don't skip; they contain the solution.
   - Read the full stack trace, line numbers, and error codes.

2. **Reproduce consistently**
   - Record exact steps to trigger the issue.
   - Determine whether it happens every time or intermittently.
   - If it is not reproducible, gather more data.

3. **Check recent changes**
   - Inspect `git diff` and recent commits.
   - Check dependencies and configuration changes.
   - Compare environment differences.

4. **Multi-component systems: add diagnostics**

   When the system has layers such as CI -> build -> signing or
   API -> service -> database, add logging at each boundary first:

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

   Run once to see where it breaks, then investigate that layer.

5. **Trace data flow backward**

   Find where the bad value originates:
   - What called this with the bad value?
   - Keep tracing to the source.
   - Fix at the source, not at the symptom.

### Phase 2: Pattern Analysis

**Find the pattern:**

1. **Find working similar code**
   - What similar path works?
   - Compare working and broken paths.

2. **Compare against the reference**
   - If implementing a pattern, read the reference completely.
   - Do not skim.
   - Understand it before applying it.

3. **Identify all differences**
   - List every difference, however small.
   - Do not assume a difference cannot matter.

4. **Understand dependencies**
   - What settings, configuration, or environment does this need?
   - What assumptions does it make?

### Phase 3: Hypothesis

Use the scientific method:

1. **Form one hypothesis**
   - State: "I think X is the root cause because Y."
   - Be specific.

2. **Test minimally**
   - Make the smallest possible change.
   - Change one variable at a time.
   - Do not fix multiple things together.

3. **Verify**
   - Worked: continue to Phase 4.
   - Did not work: form a new hypothesis.
   - Do not stack fixes.

4. **When you do not know**
   - Say: "I don't understand X."
   - Do not pretend.
   - Ask for help or research.

### Phase 4: Implementation and Verification

Fix the root cause and verify it with the user:

1. **Create a failing test** using `test-driven-development`.
2. **Implement one fix** addressing the root cause from Phases 1-3.
3. **Run tests and report results.**
4. **Ask the user to verify. This is mandatory.**

Do not assume tests passing means the problem is solved:

> Tests pass ✅
>
> Ama bu senin için çözüldü anlamına gelmeyebilir.
>
> Şunu kontrol eder misin:
> [Specific thing to check - exact steps, not vague]
>
> Çözüldü mü?

Wait for the user's response.

- User says `Evet çözüldü`: done.
- User says `Hayır`: use the progressive detail levels below.

## Progressive Detail Levels (Attempt Counter)

Track failed attempts. Increase detail after every failed fix.

### Attempt 1 Failed

When the user says the first fix did not solve the issue, respond:

> Anlıyorum, çözülmedi.
>
> Şu anda tam olarak ne oluyor?
> Ne bekliyordun?

Get brief clarification:

- What is actually happening now?
- What should be happening?
- Are there errors or unexpected behavior?

Then return to Phase 1 with the new information.

**Counter: 1**

### Attempt 2 Failed

When the second fix also fails, respond:

> İkinci deneme de olmadı. Daha detaylı konuşalım.
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
> **Senin 'çözüldü' kriterin ne?**
>
> Ne olursa 'evet çözüldü' diyeceksin?
>
> Mümkünse örnek ver: `X yapınca Y olmalı, şu an Z oluyor`.

Get deeper clarification:

- the user's exact acceptance criteria;
- an example scenario from input to expected output;
- the gap between expected and actual behavior.

Then return to Phase 1 with clearer success criteria.

**Counter: 2**

### Attempt 3 Failed

When the third fix fails, stop. Do not attempt fix number four.

This is not a simple bug. It is architectural, or the wrong problem is being
solved. Enter full pipeline analysis mode:

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
3. Parse -> Structured format conversion
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
✅ PDF in -> Final result out

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
   - Are rejections correct? Is data actually bad?
   - Format issues vs content issues

❌ Component X output quality
   [Add other unmeasured points]

───────────────────────────────────────────────────────
5. NEREDE BAŞLAYALIM?
───────────────────────────────────────────────────────

[Present investigation options]

Option A: [Component X] Quality İncele

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
10 sample PDF al, pdfplumber output'unu manuel incele,
table structure korunuyor mu ölç.

───────────────────────────────────

Option B: [Component Y] Quality İncele

Nasıl:
- [Specific approach]

Effort: [Low/Medium/High] - [time estimate]

Bulacağımız:
- [What we'll learn]

Risk:
- [What could go wrong]

Example:
Validation'ı bypass et, AI raw output'u al, manuel accuracy ölç,
browser ChatGPT ile compare et.

───────────────────────────────────

Option C: [Component Z] Audit

Nasıl:
- [Specific approach]

Effort: [Low/Medium/High] - [time estimate]

Bulacağımız:
- [What we'll learn]

Risk:
- [What could go wrong]

Example:
Validation rules'ları listele, her rule kaç reject yapıyor say,
rejected samples'ları incele; gerçekten hatalı mı?

───────────────────────────────────

Option D: End-to-End Comparison

Nasıl:
- [Specific approach]

Effort: [Low/Medium/High] - [time estimate]

Bulacağımız:
- [What we'll learn]

Risk:
- [What could go wrong]

Example:
Aynı PDF'i browser ChatGPT'ye at vs bizim sisteme at,
intermediate steps'leri compare et, nerede diverge oluyor bul.

───────────────────────────────────────────────────────
6. BENİM ÖNERİM
───────────────────────────────────────────────────────

[State your recommendation and WHY]

Örnek:

Önce Option B (AI Quality Before Validation)

Neden:
- En hızlı (30 dakika)
- Hemen gösterir: AI mı kötü, validation mı sıkı?
- Eğer AI %99 doğruysa -> validation problemi
- Eğer AI %30 doğruysa -> parse veya prompt problemi
- Diğer seçenekler sonraki adım olur

Sonra bulgulara göre Option A, C veya D'ye geçeriz.

───────────────────────────────────────────────────────
7. SONRAKİ ADIM
───────────────────────────────────────────────────────

Nereden başlayalım?

A / B / C / D / [Farklı fikir]

═══════════════════════════════════════════════════════
```

Wait for the user to choose the investigation approach. Execute the selected
investigation, report findings, then fix based on evidence.

**Counter: 3**

## Don't Blame Downstream Components

Common anti-pattern:

```text
Component A ✅ (our code, tests pass)
  ↓
Component B ✅ (our code, tests pass)
  ↓
Component C ❌ (external service, "bad output")
  ↓
Conclusion: "Component C sucks" <- WRONG
```

This is almost always wrong.

### Why Blaming Downstream Fails

When end-to-end fails but intermediate tests pass, the problem is usually:

1. intermediate quality is not measured correctly;
2. tests check existence, not quality;
3. validation is too strict or too loose;
4. bad input is sent to the external component.

The problem is rarely an undocumented, sudden degradation of the external
component.

### Correct Investigation Approach

Before blaming an external component, measure quality at every step:

```text
PDF Input
  ├─ Quality: [How to verify input is good]
  ↓
Parse
  ├─ Output quality: [Measure THIS; don't assume success = good]
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
  └─ Are rejections correct? [Is the data actually bad?]
  ↓
Final result
```

Then compare:

- good input and good external output, but validation rejects: validation issue;
- good input and bad external output: external service issue;
- bad external input: parse or preparation issue.

### Validation Transparency

When validation rejects data, do not only say `Validation failed`.

Report:

> Validation rejected X out of Y items (Z% reject rate).
>
> **Rejection breakdown:**
>
> - Rule A: 5 rejections
>   Reason: `line_item_count_mismatch`
>   Example: Expected 4 items, got 3
>
> - Rule B: 3 rejections
>   Reason: `decimal_precision_mismatch`
>   Example: 1250.0 vs 1250.00
>
> - Rule C: 2 rejections
>   Reason: `vat_group_structure_invalid`
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
> Rejected by: Rule A (expected 3 items, schema says minimum 3).
>
> Soru: Bu rejection doğru mu? Data gerçekten hatalı mı,
> yoksa validation çok sıkı mı?

Inspect rejected samples with the user before concluding that AI or parsing is
bad.

### Browser ChatGPT Works, Our System Doesn't

Symptom:

- same PDF -> browser ChatGPT -> 99% accuracy;
- same PDF -> our system -> 30% accuracy;
- conclusion: our AI call is broken.

That conclusion may be wrong. Before blaming AI integration:

1. **Inspect what is sent to AI**
   - Extract the exact prompt and data.
   - Send the same prompt and data to browser ChatGPT.
   - Verify the inputs are identical.

2. **Inspect what AI returns**
   - Capture the raw response before validation.
   - Measure content accuracy while ignoring format issues.
   - Compare it with the browser response.

3. **Inspect validation**
   - Measure pass/fail rate and rejection reasons.
   - Separate content failures from format failures.

Typical finding:

```text
AI raw output: 98% accurate (content correct)
After validation: 30% pass rate
Root cause: Validation rejects 68% for format issues
Solution: Loosen format validation or tighten the AI output specification
```

Do not jump directly to `AI integration is broken`.

## Integration with verification-before-completion

`verification-before-completion` is always active. After implementing a fix:

1. It identifies and runs the verification command.
2. Systematic debugging uses that evidence:

   > Tests çalıştırdım:
   >
   > ```text
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
   > Çözüldü mü?

3. The user confirms or denies:
   - `Evet`: done.
   - `Hayır`: increase the attempt counter and progressive detail.

Do not wait for an explicit invocation of `verification-before-completion`
before making a completion claim.

## User Signals -> Immediate Action

These phrases mean stop and change approach:

| User says | Meaning | Immediate action |
| --- | --- | --- |
| `Is that not happening?` | An assumption was not verified | Stop, run the check, and show evidence. |
| `Will it show us...?` | Diagnostics are missing | Add boundary logging, run once, then analyze. |
| `Stop guessing` | Fixes are being proposed without understanding | Return to Phase 1. |
| `This isn't working` | The definition of working is unclear | Ask for exact acceptance criteria. |
| `Try again` repeatedly | The process is looping | Count attempts; at 3, use full pipeline analysis. |
| `Neden böyle oluyor?` repeatedly | Symptoms are being fixed | Trace data backward to the source. |
| Silence | The user may be lost or frustrated | Summarize current state, objective, and unknowns. |

When any signal appears:

1. Stop the current approach.
2. Acknowledge the signal:

   > Fark ettim: [Which signal]. [What I did wrong].
   >
   > Yaklaşımı değiştiriyorum.

3. Select the new evidence-driven approach.
4. Present the new plan:

   > Yeni plan:
   >
   > 1. [What I'll do differently]
   > 2. [What output you'll see]
   > 3. [How we'll know if it worked]
   >
   > Bu yaklaşım mantıklı mı?

5. Wait for approval.

### Proactive Checkpoint

After Attempt 2 fails, do not wait for frustration:

> İki farklı yaklaşım denedim, ikisi de çalışmadı:
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
> Devam etmeden önce: Doğru şeyi mi çözmeye çalışıyorum?

Wait for clarification before Attempt 3.

## Expected Behavior Confirmation

Before implementing a fix for a feature that does not work, confirm expected
behavior:

> Fix yapmadan önce expected behavior'ı confirm edelim:
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
> Bu beklentini karşılıyor mu?

Wait for confirmation. If the user says no, restate the expectation and iterate
until the user says `evet, aynen öyle`. Then implement.

## Verification Checklist

Before claiming the bug is fixed:

- [ ] Root cause identified, not only the symptom.
- [ ] Regression test created with RED -> GREEN using
      `test-driven-development`.
- [ ] One root-cause fix applied.
- [ ] Tests pass.
- [ ] User was asked `Çözüldü mü?`
- [ ] User confirmed `Evet çözüldü`.

If any item is unchecked, the issue is not done.

## Red Flags

- `Quick fix for now`
- `Just try X and see`
- Adding multiple changes together
- Skipping the test and relying on manual verification
- `Probably X, let me fix it`
- Proposing a fix without understanding the data flow
- `Tests pass, so it's fixed` without user confirmation
- `One more fix` after three attempts
- Each fix reveals a new problem elsewhere

All mean: stop and follow the phases.

## Common Rationalizations

| Excuse | Reality |
| --- | --- |
| `Issue is simple; no process needed` | Simple issues still have root causes. |
| `Emergency; no time` | Systematic investigation is faster than thrashing. |
| `Just try this first` | The first random fix starts the wrong pattern. |
| `Tests pass = fixed` | The user defines fixed, not the test suite. |
| `Write the test after confirming` | Untested fixes do not prevent regressions. |
| `Multiple fixes save time` | They hide which variable mattered. |
| `Reference is too long` | Partial understanding produces more failures. |
| `One more fix` after three attempts | Three failures require pipeline analysis. |
| `External component must be bad` | Measure intermediate quality first. |

## Integration with Other Skills

Use with:

- `test-driven-development`: create the regression test in Phase 4.
- `verification-before-completion`: gather fresh evidence before claiming done.

Do not:

- skip root cause investigation because of an emergency;
- stack fixes without verification;
- claim fixed without user confirmation;
- blame external components without measuring intermediate quality.

---

**End of Systematic Debugging Skill**
