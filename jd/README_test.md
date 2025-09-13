# Test Data Bundle (Live Mode)

This bundle contains a sample Job Description (JD), a sample Resume with phone number, and a prefilled `.env.test`.

## Files
- jd/sample_jd.pdf → Example Job Description (Python Backend)
- candidates/rahul_resume.pdf → Resume with +917709861994
- .env.test → Environment configuration (LIVE MODE, will call real number if Twilio configured)
- README_test.md → This file

## Usage
1. Copy contents of this bundle into your repo root.
   ```bash
   unzip test_data_bundle.zip -d ai_recruitment_full_repo
   cd ai_recruitment_full_repo
   ```

2. Copy `.env.test` → `.env` and fill in Twilio + DB credentials.

3. Start backend:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```

4. Expose via ngrok:
   ```bash
   ngrok http 8000
   ```

5. Update Twilio voice webhook with:
   ```
   https://<PUBLIC_SERVER_URL>/voice
   ```

6. Open dashboard:
   ```
   http://localhost:8000/dashboard
   ```

7. You will see JD + Rahul's resume loaded.  
   Run shortlisting → Start Calls → System will attempt to call +917709861994.
