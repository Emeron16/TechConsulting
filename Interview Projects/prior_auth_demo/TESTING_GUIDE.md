# Test Guide: Three Strategic AI Opportunities

Use this guide to rehearse the prior-authorization demo and record whether each capability works. Use the supplied synthetic cases as the source of truth. The policies in this project are synthetic demo rules.

## Before you start

1. Open a terminal in `prior_auth_demo` and start the app with the Python environment that contains its dependencies:

   ```bash
   /opt/anaconda3/bin/python -m streamlit run app.py
   ```

   This is the Anaconda interpreter used on this Mac. In another configured environment, use `python -m streamlit run app.py`.

2. Ensure the project's `.env` contains a working `OPENAI_API_KEY`. Extraction, policy analysis, and letter generation call the live model.
3. After clearing demo data, refresh the browser. **Provider Portal** should say “No requests submitted yet. Start on New Request.” **Nurse Dashboard** should have no queued requests, and **Analytics & Audit** should have no live requests or audit entries. The proposal's static charts still appear.
4. Record every new request ID. Each click on **Run Intake Pipeline** creates a new request. Submitting additional documentation in **Provider Portal** updates the selected request.
5. Capture results before navigating away from **New Request**; its step-by-step output is displayed on the submission run. Saved status, letters, and audit events remain accessible on the other pages.

## Strategy 1: Multi-Modal Document Extraction & Intake

**Question:** Can an uploaded document become accurate structured clinical data?

Selecting a sample case tests AI extraction from existing text. To demonstrate document intake, upload an actual PDF or image.

### Prepare the documents

1. Open [sample C — knee arthroscopy](data/sample_requests/C_knee_arthroscopy_fast_track.txt).
2. Copy its complete contents into a document editor, such as Word or Google Docs. Export it as `C_knee_arthroscopy.pdf` with selectable text.
3. Make a readable PNG/JPG image of the same document, including all patient details and clinical notes. A screenshot is sufficient for the image test. If it will not fit legibly, reduce page margins or use a full-page image instead of cutting off text.
4. Keep the original text file open as your answer key. Do not use the solution proposal PDF as a patient intake packet.

### Test 1A: PDF upload

1. Open **New Request**.
2. Select **Upload PDF / image** and upload `C_knee_arthroscopy.pdf`.
3. Compare **Extracted text (editable before processing)** with the source. For the first run, leave extraction errors uncorrected so you can evaluate the actual output.
4. Click **Run Intake Pipeline**.
5. Expand **Step 1 — Document Extraction** and compare the output with this answer key:

| Field | Expected value from sample C |
|---|---|
| Patient ID | `MEM-65590212` |
| Date of birth | `01/30/1990` or an equivalent normalized date |
| Provider | Dr. Elena Petrov, MD — Riverside Orthopedic Associates |
| Ordering NPI | `1620394857` |
| Diagnosis codes | `S83.241A`, `M25.561` |
| Procedure code | `29881` |
| Urgency | `routine` |
| Clinical notes | Right knee symptoms, MRI-confirmed tear, five-week treatment course, ongoing locking, and missing exact treatment dates preserved |

**Pass:** All listed fields match the source and clinical details are preserved without invented facts. A high confidence score alone does not establish correctness.

**Evidence:** Save the request ID, source PDF, extracted-text screenshot, and Step 1 screenshot. Note any incorrect or omitted fields.

### Test 1B: Image OCR

1. Confirm the Tesseract binary is available by running `tesseract --version` in the terminal used to start the app. If it is missing on this Mac, install it with `brew install tesseract`, then restart the app.
2. In **New Request → Upload PDF / image**, upload the PNG/JPG version.
3. Inspect the extracted text before running the pipeline. Check codes and identifiers especially carefully for OCR substitutions.
4. Click **Run Intake Pipeline** and compare Step 1 with the same answer key.

**Pass:** OCR recovers the document content and structured fields match the source. If Tesseract is unavailable, record the OCR test as **blocked**, not passed.

**Boundary test:** Upload a PDF containing only a scanned image and no text layer. The current app should show a no-extractable-text warning and prevent submission of empty text. Scanned-PDF OCR is not implemented; image OCR is available through PNG/JPG uploads.

**Pitch line:** “The uploaded document becomes structured patient, provider, and procedure data that downstream checks can use.”

## Strategy 2: Automated Completeness & Pre-Check

**Question:** Does the system identify missing documentation before the packet reaches a nurse, and can the provider supply it?

### Known defect in the original sample B

The current completeness validator uses keyword matching. In [sample B — incomplete lumbar MRI](data/sample_requests/B_mri_lumbar_incomplete.txt), this sentence contains treatment keywords even though it says documentation is missing:

```text
(No documentation of physical therapy, medication trial, or other conservative management
provided in this submission.)
```

The original wording has been observed to pass incorrectly. The workflow test below uses a workaround; passing it does not resolve the keyword-negation defect.

### Test 2A: Missing documentation blocks the packet

1. Open **New Request → Sample case**.
2. Select **B — Lumbar MRI, missing conservative treatment**.
3. In **Document text (editable)**, delete only the final parenthetical quoted above. Leave the remaining notes unchanged. This removes the misleading keyword matches without adding any treatment evidence.
4. Click **Run Intake Pipeline** and record the request ID.
5. Scroll below Step 1 to **Step 2 — Completeness Validator**.
6. Confirm that the result lists:
   - **Incomplete**, with `conservative_treatment` missing.
   - Matched policy `MRI-LUMBAR-001`.
   - A missing-information letter requesting treatment documentation.
   - A message that the pipeline stopped; Steps 3 and 4 should not run.
7. Open **Provider Portal**, select this request, and confirm **Information Requested** and the letter.
8. Open **Nurse Dashboard** and confirm this request is absent from the review queue.
9. In **Analytics & Audit**, filter by this request ID. Before resubmission, expect only **Document Extraction**, **Completeness Validator**, and **Missing-Information Letter** events.

**Pass:** The request stops with `information_requested`, identifies the missing item, saves a letter, and does not reach policy analysis or nurse review.

**Evidence:** Capture Step 2, the letter, the request ID, and the filtered audit trail.

**Previously verified:** On September 14, 2026, this edited input passed a live pipeline check, including saved status, missing item, letter, and audit events. This was a pipeline/database check, not a browser walkthrough. Its saved test record may no longer exist after the demo reset.

### Test 2B: Supply the missing documentation

1. In **Provider Portal**, select the incomplete request from Test 2A.
2. Paste the following synthetic test addition into **Additional documentation / clarifying notes from the provider**:

   ```text
   The patient completed eight weeks of physical therapy and a six-week NSAID
   trial without improvement. Persistent radiculopathy continues. No MRI
   contraindications are documented.
   ```

3. Click **Submit additional documentation**.
4. Confirm the same request ID now shows **Under Review** (`queued_for_review`). The MRI policy is not eligible for auto-approval.
5. Open **Nurse Dashboard** and confirm the request is available for human review.
6. In **Analytics & Audit**, verify that new extraction, completeness, policy-analysis, and routing events were appended for the same ID.

**Pass:** The supplemented request passes the documentation check and proceeds to human review without creating a second request. The exact review pathway and AI wording can vary.

### Test 2C: Record the unresolved negation defect

Submit a separate copy of the original, unedited sample B. It should also be classified as incomplete. If it passes, record a **failed test: negated treatment documentation counted as present**. Do not count Test 2A's workaround as a pass for this test.

**Pitch line:** “The pre-check returns an actionable request for missing information before nurse review, and the provider can resubmit it through the portal.”

## Strategy 3: AI-Assisted Clinical Decision Support

**Question:** Can a reviewer verify the AI's summary and policy comparison, then make a traceable decision?

### Test 3A: Review the AI's work

1. Use the sample C request created by the PDF upload in Test 1A. If necessary, submit sample C again and record its new ID.
2. Check **Step 3 — Policy RAG Analysis** for matched policy `KNEE-ARTHRO-001`.
3. Compare the summary, met/unmet criteria, citations, and focus areas against [sample C](data/sample_requests/C_knee_arthroscopy_fast_track.txt) and the [knee policy](data/policy_kb/KNEE-ARTHRO-001.json).
4. Check that the analysis reflects the documented tear, symptoms, treatment trial, and persistent locking. It must not invent exact physical-therapy start/end dates, which the source omits.
5. In Step 4, confirm **Human review required: Yes**. Sample C is intended for **Fast-Track**; **Standard Review** can occur depending on the AI's analysis. Record the actual pathway and reason. Auto-approval is a failure for this policy.
6. In **Provider Portal**, confirm the case is **Under Review** and no final decision has been issued.
7. Open **Nurse Dashboard** and select that request. Verify the AI summary, recommendation, criteria, and citations are available alongside the extracted notes.

**Pass:** The analysis is grounded in the supplied source and demo policy, uncertainty remains visible, and the request awaits a human decision. Record incorrect summaries, unsupported citations, and invented details as failures even if routing succeeds.

### Test 3B: Record a human decision

1. Enter `Demo Nurse` in **Nurse name (for the audit trail)**.
2. Enter reviewer notes, for example: `Synthetic demo: reviewed the source notes and matched policy; recording approval to test the workflow.`
3. Click **Approve** to exercise the approval path for this synthetic case.
4. Confirm the case leaves the nurse queue.
5. Open **Provider Portal** and select the same ID. Confirm **Decided**, **APPROVED**, reviewer `Demo Nurse`, and a decision letter consistent with the recorded decision.
6. In **Analytics & Audit**, filter by the same ID and confirm a **Nurse Decision** event with actor **human**, reviewer name, decision, and notes.

**Pass:** The final status, letter, and audit trail agree with the human action. The AI recommendation alone did not finalize the case.

**Optional control checks:** On a separate undecided copy of C, leave the nurse name blank and click **Approve**; expect an error and no decision. On another copy, exercise **Deny** and verify the portal and audit show the human's chosen decision even if the AI recommended approval.

**Pitch line:** “The AI prepares a summary and policy comparison; the nurse makes the decision, with the action recorded in the audit trail.”

## Additional scenarios

| Sample | What to check |
|---|---|
| [A — physical therapy](data/sample_requests/A_pt_eval_auto_approve.txt) | Separate low-risk auto-approval pathway, if all routing conditions are satisfied. It does not demonstrate nurse validation. |
| [D — bariatric surgery](data/sample_requests/D_bariatric_standard_review.txt) | Intended complex-review scenario; inspect risk flags, unmet criteria, and reviewer focus areas. Record the actual route. |
| [E — urgent CTA](data/sample_requests/E_cta_chest_urgent_stat.txt) | For a packet that passes completeness, urgency should route it to Urgent / STAT with human review required. |

## Record the results

Fill this in during rehearsal. Only Test 2A's earlier pipeline check is verified above; the other rows are procedures to execute, not claims that they have passed.

| Test | Request ID | Pass / Fail / Blocked | Evidence or defect |
|---|---|---|---|
| 1A — PDF upload and structured extraction | | | |
| 1B — Image OCR and structured extraction | | | |
| 2A — Missing documentation stops intake | | | |
| 2B — Provider resubmission proceeds to review | | | |
| 2C — Negation handled correctly | | Known defect | Original sample B can incorrectly pass |
| 3A — Grounded summary and human review required | | | |
| 3B — Human decision, letter, and audit agree | | | |

## Fifteen-minute presentation sequence

| Time | Demonstration |
|---|---|
| 0–2 minutes | Explain the intake problem and three opportunities. |
| 2–5 minutes | Upload sample C as a PDF; show source text and structured fields. Show the image-OCR result from rehearsal if time permits. |
| 5–9 minutes | Run edited sample B, show the missing-information flag and letter, then submit the additional documentation. Disclose the keyword-check limitation. |
| 9–13 minutes | Review the sample C case, record a nurse decision, and show the portal and audit trail. |
| 13–15 minutes | Explain what the demo proves and the measures needed for a pilot. |

Have screenshots available from rehearsal in case a live API call is slow. Label them as earlier results.

## What the demo can establish

- **Extraction:** Compare correct required fields with total required fields across PDF and image inputs; count invented or missing details separately.
- **Completeness:** Measure whether known omissions are detected and whether complete packets are incorrectly blocked. The implementation is a deterministic keyword pre-check, not a trained predictive rework model. It does not reliably handle negation, treatment duration, or policy exceptions.
- **Decision support:** Check summary accuracy, policy grounding, human decision controls, and consistency of letters and audit events. Model confidence and estimated review minutes are not measured accuracy or observed review time.
- **Business impact:** The 22% rework rate is a proposal baseline. Static projected charts do not prove a reduction. The live “rework rate” is the share of saved requests currently in `information_requested`; it is not a historical measure of all cases that ever required rework. A pilot needs observed review times and comparable before/after rework measurements.
- **Communication:** Letters are generated and stored in the demo portal. The app does not send real faxes or emails, despite some UI labels describing a letter as “sent.”
