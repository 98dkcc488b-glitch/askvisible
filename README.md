# AskVisible — Weekly AI visibility report (self-hosted)

Every Monday, this repo asks Google Gemini a handful of prompts your buyers would
plausibly type ("best alternative to X", "which tools do indie devs use for Y") and
tells you whether your brand (and your competitors) came up — and in what position.

The result is an HTML report that lands in your inbox. No dashboard. No subscription.
Clone it, add your Gemini key, done.

## What's in the box

- `run.py` — the generator. Reads `config.json`, calls Gemini for every prompt,
  analyses whether your brand got a mention, writes `reports/report.html`.
- `config.example.json` — fill in your brand, your 3 competitors, 5 prompts.
- `.github/workflows/weekly.yml` — GitHub Action that runs every Monday 08:00 UTC
  and optionally emails the report.
- `samples/` — a real example report (brand: Linear, Oct 2026).

## Setup (one-time, 10 minutes)

1. **Click "Use this template" → create a new private repo** on your own GitHub.
2. **Get a Gemini API key** (free): [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
3. **Add the key as a GitHub secret**:
   Repo → Settings → Secrets and variables → Actions → New secret
   - Name: `GEMINI_API_KEY`
   - Value: (paste the key)
4. **Edit `config.json`**: brand name, up to 10 competitors, 5–10 prompts the way
   your prospects would ask Gemini. Commit.
5. **Enable the workflow** under the Actions tab (GitHub asks once).

That's it. The workflow runs every Monday at 08:00 UTC and uploads the report as
an artifact you can download. See "Email delivery" below if you'd rather get it
by mail.

## Email delivery (optional)

Add these secrets if you want the workflow to email the report:

| Secret | Example |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `you@gmail.com` |
| `SMTP_PASSWORD` | *Gmail app password — [create one](https://myaccount.google.com/apppasswords)* |
| `SMTP_FROM` | `you@gmail.com` |
| `SMTP_TO` | `you@gmail.com` |

The workflow uses `dawidd6/action-send-mail` and attaches `reports/report.html`
as the message body. Works with Gmail, Fastmail, Mailgun SMTP, Postmark, etc.

Prefer Slack or Discord? Replace the email step with a webhook — the generator
also writes `reports/summary.json` with the headline numbers.

## Running it locally

```bash
cp config.example.json config.json
# edit config.json
export GEMINI_API_KEY=…
python run.py
open reports/report.html
```

Python 3.10+, standard library only. No pip dependencies.

## Writing good prompts

The report is only as useful as the prompts. A few patterns that work:

- `"What are the best alternatives to <bigger competitor> in 2026?"`
- `"I'm looking for a cheap tool to do <your category>. Recommendations?"`
- `"What tools do <your audience, e.g. indie hackers> use for <job>?"`
- `"Compare the top 5 <category> tools — short pros and cons."`
- `"What's a good lightweight alternative to <market leader>?"`

Avoid branded prompts ("Is <your brand> any good?") — the point is to see whether
Gemini surfaces you *unprompted* when your prospects go looking.

## FAQ

**Why only Gemini, not ChatGPT and Claude?**
Honesty: Gemini is the one engine with a generous free tier that lets a $19
one-time product cover real usage. ChatGPT, Claude and Perplexity would push
costs past what the price supports. If you want all four, pay $100–500/mo for
Profound, Peec, or Otterly.

**How accurate is the position number?**
We parse markdown headings and top-level numbered lists. If Gemini answers in
prose, we report mention count instead of a rank. If Gemini puts you in a
nested bullet under a competitor, that still counts as "mentioned."

**Can my prompts change over time?**
Yes — just edit `config.json` and commit. The next Monday run picks it up.

**What's the API cost?**
Default model `gemini-flash-latest` + 5 prompts/week = well below the free tier
(1,500 requests/day). You can run this for free, forever.

**Why self-hosted and not a hosted dashboard?**
Keeps the price at $19 one-time, keeps your prompts private to you, and the
report lives in your repo history for free week-over-week comparison.

## Changing engines

Edit `config.json` → `"model": "gemini-3.6-flash"` (or any other model listed at
[ai.google.dev/models](https://ai.google.dev/gemini-api/docs/models)). The runner
also falls back to `gemini-3.6-flash`, `gemini-3.5-flash`, and
`gemini-flash-latest` automatically if the primary model is rate-limited.

## License

Source: MIT. Buy the Gumroad product once ($19), use on any number of brands
you own forever. Resale or re-publishing not allowed.

Questions / bugs: open an issue on this repo.
