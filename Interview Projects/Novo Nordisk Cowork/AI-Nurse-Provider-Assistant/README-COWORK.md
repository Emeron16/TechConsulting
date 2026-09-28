# Complete prior authorization demo — Cowork edition

**Open:** http://127.0.0.1:8771/

This is the complete application, copied from the original OpenAI demo. It replaces the smaller portal at port 8770 as the main demonstration.

## Start the demonstration

1. Start this app using `./start.command` (or `/opt/anaconda3/bin/python -m streamlit run app.py` from this directory).
2. In the existing **Prior authorization demonstration** Cowork conversation, start **run-full-app-session**. Keep the connected demo folder and desktop session available.
3. Wait for **Cowork session connected** in the app sidebar. Present only the app. One session instruction handles successive submissions and nurse actions for up to 15 minutes; do not chat with Cowork while it is processing.
4. Use **New Request**, **Request Status**, **Nurse Dashboard**, and **Analytics Audit** as in the original app. The overview still labels proposal figures as assumptions and targets.

If the skill is not visible in an older conversation, the session instructions are in `../plugin/prior-auth-review/skills/run-full-app-session/SKILL.md` within the connected demo folder.

## Feature coverage

| Original feature | Cowork edition |
|---|---|
| Themed overview and proposal charts | Copied |
| Provider submission: five samples, pasted text, PDF/image upload | Copied; PDF extraction and Tesseract OCR retained |
| Structured extraction | Live Cowork job; Pydantic validation |
| Completeness and six-policy retrieval | Original deterministic implementation |
| Policy analysis, summaries, reported confidence | Live Cowork job |
| Auto-approval, urgent, fast-track, standard routing | Original rules and thresholds |
| Nurse approve, deny, request more information | Copied; letter drafting now runs in Cowork |
| Provider final status, letters, additional documentation | Copied |
| SQLite persistence, audit records, actual activity analytics | Copied, separate database |
| Reset with confirmation and database backup | Copied |

No API key, OpenAI call, Claude Code runtime, or recorded-response replay is used. `core/cowork_bridge.py` hands the app's AI prompts and response schemas to an active Cowork session. Cowork writes fresh outputs and the app continues its existing workflow. All decisions and letters are synthetic simulations. Letters are not externally sent.

## Verification

Eight requests were processed live through Cowork, including the pending bariatric upload from the earlier portal. All five original samples completed. The urgent sample routed urgent; the original PT, MRI, knee, and bariatric samples routed standard in this run. A PDF with missing identifiers correctly entered information requested. A clean evaluation-only PT document still received standard review from Cowork.

All three nurse actions were exercised through Streamlit's AppTest against the live Cowork worker; their resulting letters and statuses persisted. Provider follow-up reprocessed the same case, and approval/denial letters rendered on Request Status. Image OCR extracted the sample procedure code. All four workflow pages rendered without exceptions. Eight queue/routing tests passed, including auto-approval threshold, risk blocking and urgent override. Reset was tested only on a temporary database; its backup retained the prior request. Browser inspection confirmed the actual nurse and provider pages.

Detailed evidence is in `verification/*.json`. The demonstration database retains these synthetic test cases. Use Analytics Audit's reset control when you want a clean run.

## Important parity limits

Feature parity does not guarantee identical model outputs. Cowork flagged ambiguous frequency language, missing procedure detail, and inconsistent ages in some original samples. Do not promise that a sample labeled auto-approval or fast-track will take that path. Auto-approval and fast-track are verified as deterministic rule branches, but neither was produced by the live Cowork examples in this verification.

The original completeness checker uses keyword presence. For example, “no documentation of physical therapy” can still satisfy its treatment-documentation keyword test. This inherited limitation remains, and the original incomplete MRI text was therefore routed for review; use the tested missing-identifiers PDF to demonstrate the missing-information branch. Scanned PDFs still require a text layer. These limitations are not silently represented as solved.

Cowork must remain active. Sleep, disconnect, new chat messages, or the session limit can interrupt work; the app times out rather than inventing a response. Session status is a recent-contact indicator, not a permanent service guarantee. This local demo does not implement production user authentication or compliance certification.

Original repository, credentials, database, and backups were not modified or copied into this edition. Only app source, policies, and sample documents were copied. The local Streamlit file watcher is disabled after it caused a macOS crash; restart the server after code edits.
