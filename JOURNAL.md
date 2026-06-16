# Tattoo Booking Tracker — Journal

## TODO

- **Email on Railway**: Gmail SMTP port 587 is blocked by GCP (Railway's infrastructure). Switch to an HTTP-based provider — Resend is the easiest (free tier, 2min setup). Needs `RESEND_API_KEY` env var and a verified sending domain.

## Notes

- Instagram session cookie must be kept fresh — it expires and needs manual replacement in Railway env vars.
- Playwright headless Chromium used for scraping `/?variant=following` (chronological following feed). Mobile API `/feed/timeline/` is algorithmic only.
- Check frequency: every 2 hours, 48h lookback window.
