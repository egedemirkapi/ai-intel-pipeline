# Troubleshooting

Real problems hit during development + their fixes. Look up your error here before opening an issue.

---

## Email problems

### Resend error: "You can only send testing emails to your own email address"

**Cause:** Resend's free tier sandbox restricts you to sending only to the email you registered the account with, until you verify a domain.

**Fix (quickest):** Make sure `EMAIL_TO` in `.env` matches the email you used to sign up at resend.com.

**Fix (proper):** Verify a domain at [resend.com/domains](https://resend.com/domains). Add the 3 DNS records, wait ~5 min for verification, then update `src/ai_intel/mailer/send.py` to use `from = "intel@yourdomain.com"`.

---

### Resend says "delivered" but no email in Gmail inbox

Check your **Spam folder** first. Sandbox sender (`onboarding@resend.dev`) often gets flagged.

If found in Spam:
- Mark as "Not spam"
- Search Gmail for `from:onboarding@resend.dev` and add a Gmail filter to never mark as spam

---

### Email bounced with "552-5.7.0 This message was blocked because its content presents a potential security issue"

**Cause:** Gmail's malware filter triggered on security-sensitive terms in article titles (e.g. "macOS kernel exploit"). This happens with real AI news — exploit research, security disclosures, etc.

**Fix:** Already mitigated in the codebase — the full digest is embedded in the email HTML body, so even if the PDF gets blocked you can still read the content inline.

**Permanent fix:** Verify a custom domain at Resend (better sender reputation = fewer false positives).

---

## Anthropic API problems

### `401 Unauthorized: invalid x-api-key`

**Cause:** Your OAuth token from `claude setup-token` expired (they're short-lived) OR you have an old/invalid key in `.env`.

**Fix:**
1. Run `claude setup-token` in a fresh terminal
2. Copy the new token (starts with `sk-ant-oat01-...`)
3. Open `.env`, replace the `ANTHROPIC_API_KEY=...` line
4. Restart the pipeline

**Permanent fix:** Get a real API key from [console.anthropic.com](https://console.anthropic.com). Costs ~$5–10/month at default settings (Haiku). Real keys don't expire.

---

### `429 Too Many Requests` from Anthropic

**Cause:** Your Claude MAX plan rate limit is shared between this pipeline AND any active Claude Code sessions. If both are running hard, the model you're using will 429.

**Fix:**
1. Check `config/config.yaml`. Default `analyst_model` is `claude-haiku-4-5-20251001` (very generous limits). If you changed it to Sonnet or Opus and are also using Claude Code, switch back to Haiku.
2. If still 429-ing on Haiku, your overall MAX quota is exhausted for the day. Wait for quota refresh OR switch to a real API key.

The pipeline handles 429 gracefully — it falls back to pre-score ranking (no model call) and still sends a digest with headlines.

---

## Setup problems

### `source: command not found` on Windows

You're in PowerShell. Use:
```powershell
.\.venv\Scripts\Activate.ps1
```

Or call the venv's Python directly:
```powershell
.\.venv\Scripts\python.exe -m ai_intel
```

If PowerShell complains about execution policy:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

### `WeasyPrint failed to load library 'libgobject-2.0-0'`

**Cause:** WeasyPrint needs GTK runtime libs that aren't installed on Windows by default.

**Fix:** The codebase swapped to Playwright for PDF rendering. If you're on the latest version, just run:
```bash
playwright install chromium
```

If you cloned an older commit, `pyproject.toml` should already list `playwright>=1.40.0` instead of weasyprint. Reinstall:
```bash
pip install -e ".[dev]"
playwright install chromium
```

---

### `No module named ai_intel`

You're using the system Python, not the venv Python. Either:
- Activate the venv first: `.\.venv\Scripts\Activate.ps1`
- OR call venv Python directly: `.\.venv\Scripts\python.exe -m ai_intel`

---

## Pipeline runtime problems

### "No items to digest this cycle"

**Cause(s):**
- Genuinely no fresh items in the time window (some 2h windows are quiet)
- All items in window were already sent in a previous digest (deduplication working as intended)
- Enrichment failed (check logs for 401/429 errors)

**Verify:** Check `data/items.db` — open in any SQLite viewer. If there are items with `classification IS NULL`, enrichment failed. If there are items with `sent_in_digest_at IS NOT NULL`, dedup is working.

---

### Same items every cycle / repeat content

**Cause:** Pipeline crashed before marking items as sent.

**Fix:** Delete the DB and restart:
```bash
rm data/items.db data/.started
python -m ai_intel
```

The 24h backfill will run again.

---

### Some RSS feeds 404 (a16z, Anthropic, Bens Bites)

These feeds occasionally change URLs or go offline. The pipeline logs an ERROR but continues processing other sources. Currently disabled in default config:
- `rss_a16z` — a16z removed their public RSS
- `rss_anthropic` — feed.xml 404s

To re-enable when fixed, uncomment them in `config/config.yaml` under `sources.enabled`.

---

### Empty digest with "Limited analysis" header

**Cause:** Analyst model failed (429, malformed JSON, etc.) and the pipeline fell back to pre-score ranking.

**Fix:** Look at the previous log lines for the actual error. Usually a 429 or auth issue. See those sections above.

---

## Deployment problems

### Render service keeps sleeping

You're on the Free tier. Free tier sleeps after 15 min of inactivity, which breaks the 2h scheduler. Switch to Starter ($7/month) for always-on.

---

### Render deploy succeeds but no emails arrive

Three things to check:
1. Did you set ALL three env vars in the Render dashboard? `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `EMAIL_TO`
2. Is the persistent disk mounted? Without it, `data/.started` doesn't persist between deploys, causing a fresh backfill on every deploy.
3. Check Render logs for the same errors as local (401, 429, etc.)

---

## Still stuck?

Open a GitHub issue with:
- Your OS (Windows / macOS / Linux)
- Python version (`python --version`)
- Whether you're using OAuth token or real API key
- The last ~30 log lines (mask any API keys before pasting)

Or DM @egedemirkapi.
