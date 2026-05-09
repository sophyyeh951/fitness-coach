# fitness-coach — Claude / agent context

LINE bot for personal fitness coaching (food/exercise/body logging + AI coach).
Owner is non-engineer; communicate in Traditional Chinese (台灣用語).

## Production

- **Live URL**: `https://fitness-coach-us.onrender.com`
  - ⚠️ Old URL `https://fitness-coach-hv3f.onrender.com` was the singapore service (defunct after 2026-05-09 Gemini-region migration).
  - ⚠️ NOT `https://fitness-coach.onrender.com` (unrelated / dead).
- **Health check**: `GET /health` → `{"status":"ok"}`
- **Version check**: `GET /version` → `{"sha":"<short-sha>"}`
- **Hosting**: Render free tier, region **oregon**, Python 3
  - ⚠️ **MUST be in a US region.** Singapore (and likely all asia regions) gets `400 FAILED_PRECONDITION: User location is not supported` from Gemini API. Originally created in singapore 2026-04-02; migrated to oregon 2026-05-09 after `/吃` text parse failures traced to this. Don't recreate in asia.
  - 512MB RAM ceiling — exceeded once (PR #15 fixed Pillow/matplotlib leaks)
  - Free instances spin down after ~15min idle; cold start 50–90s
  - Auto-deploys from `main` branch on push
- **Keep-alive**: `.github/workflows/keep-alive.yml` pings `/health` every 14 min during Taiwan waking hours

## Stack
- FastAPI + uvicorn (single worker)
- Supabase (Postgres) for storage
- Google Gemini (`gemini-2.5-flash`) for vision + coach text
- LINE Messaging SDK v3
- APScheduler for morning/evening/weekly cron (in-process; **does NOT prevent Render spin-down**)
- matplotlib (Agg backend) for trend charts

## Workflow rules
- **Branch protection**: direct push to `main` is blocked. Always go via PR + squash merge.
- **Deploy = merge to main** → Render auto-deploys (~2-3 min build)
- After merging, verify with `curl https://fitness-coach-us.onrender.com/health` (give 60-90s for cold start)
- Owner authorises autonomous deploy by default (see memory `feedback_deploy_visibility.md`).
  Exceptions requiring explicit confirmation: DB destructive ops, secrets changes, force-push.

## Common pitfalls
- **Memory**: any new image-processing or chart code MUST close `Image`/`BytesIO`/`Figure`. The 512MB ceiling is real and unforgiving.
- **Don't trust the in-process keep-alive** for spin-down prevention — it dies with the process. External cron only.
- **URL guessing**: never assume `<service-name>.onrender.com`. Check Render dashboard.
