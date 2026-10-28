# ZENQORY — Premium Telegram Mini App

**An original black × neon-green, futuristic digital rewards experience.**

Mobile-first Telegram Mini App built with luminous crystal environments, an original Z coin, glass-style panels, high-contrast typography, progress rings and five navigation screens.

**Important:** ZNQY Points are off-chain pre-launch rewards, **not cryptocurrency**. There is no live ZNQY token, cash value, exchange listing, withdrawal mechanism or guaranteed airdrop.

## Screens

| Screen | Includes |
|---|---|
| Home | Rewards balance, eight-hour farming and claim, progress timer, daily reward, tasks, referrals and wallet preview |
| Earn | Mission progress, self-claim educational tasks, bonuses and upcoming campaigns |
| Friends | Invite link, copy/share actions, referral metrics, network graphic and program explanation |
| Wallet | Off-chain points vault, recent reward activity and disabled on-chain actions while integration is pending |
| Profile | Telegram name, stats, account options, achievements preview and help |

## Reward Rules

- Farming: start an **8-hour** cycle; after the full period the user can claim **80 points**. One active cycle maximum.
- Daily claim: **20 points** once per rolling 24-hour window.
- Educational tasks: **30, 20 and 15 points** per mission once per account.
- Referral: **10 points** to the inviter after the invited member successfully claims their first farming cycle.
- Every real reward mutation is protected by a database transaction and verified Telegram session.

## Stack

- Frontend: public/index.html + public/styles.css + public/app.js
- Graphics: public/hero-art.svg and public/favicon.svg
- Backend: server.py (FastAPI)
- Persistence: PostgreSQL (external managed database)
- Hosting: Vercel (FastAPI auto-detection; public directory served by CDN)
- Identity: Signed Telegram Mini App initData validated with BOT_TOKEN on the server

## How to deploy: GitHub → Vercel → Telegram

1. Open https://vercel.com/new and import GitHub repository **smbabanbaba-maker/Crypto-**.
2. Keep project root as the repository root; Vercel automatically detects the FastAPI app inside **server.py**. No custom build command or vercel.json is necessary.
3. Set up an external PostgreSQL database using Neon, Supabase or the Vercel Marketplace.
4. In Vercel → Project Settings → Environment Variables, add: **DATABASE_URL** (PostgreSQL connection string), **BOT_TOKEN** (BotFather secret token) and **BOT_USERNAME** (without the @ prefix). Keep them in Vercel only, NEVER in GitHub.
5. Deploy. Test the HTTPS root URL to view the demo; test **/api/health** to verify the backend.
6. Go to https://t.me/BotFather and create or configure the ZENQORY bot. Set its **Menu Button** or **Main Mini App** URL to your Vercel production HTTPS URL.
7. Open from Telegram and test sign-in, farming, daily claims, and the referral flow using two different Telegram accounts.

## Demo mode

An ordinary browser provides a labelled localStorage demo, with a preview-only option to complete a cycle. Browser demo points are **not** uploaded to the production database and are not cryptocurrency.

When launched within Telegram, the app uses signed Telegram initData; the server validates the signature and session date before authorizing any account or rewards action.

## Local run

Requires Python 3.10+ and a working installation of dependencies from requirements.txt.

1. Create and activate a Python virtual environment.
2. Install dependencies using pip install -r requirements.txt.
3. Start with uvicorn server:app --reload.
4. Open http://127.0.0.1:8000 in a browser.

## Before public launch

This repository is a **functional MVP**, not an audited or publicly launched cryptocurrency protocol. Before a community-scale launch, add separate database migrations, security review, rate limiting, Sybil/abuse controls, monitoring, backups, privacy policy, reward terms and compliance assessment. The wallet is a roadmap/placeholder, not a working TON wallet; no deposit/withdrawal/token sale is offered.

Validate ZENQORY and ZNQY availability, brand rights and domains before promoting the platform. Do not imply the points have any guaranteed cash value or future token exchange rate.

References: https://vercel.com/docs/frameworks/backend/fastapi • https://core.telegram.org/bots/webapps • https://docs.ton.org/ecosystem/ton-connect


## ✨ Cyber Upgrade V2 — 26 October 2026

The interface now has five connected cyber command screens with **25 CSS keyframe animations** and a refined, compact mobile layout.

- **Home:** animated ZNQY coin and orbital fields, glowing HUD corner brackets, 8-hour farming chamber, real cycle/progress telemetry, user-only activity feed and smaller mission cards.
- **Earn:** holographic mission channels, responsive energy wave, actual completed-mission state, animated progress and mission-ready cards.
- **Friends:** neon network topology, circuit graphics and referral counts derived from registered users rather than invented leaderboards.
- **Wallet:** luminous digital vault, off-chain reward ledger, activity and secure-by-design future TON wallet placeholder. Deposits and withdrawals remain unavailable.
- **Profile:** futuristic identity console, progress-to-next-explorer-level rail and visibly locked/unlocked badges based on actual completed activities.
- **Global:** original cyber-circuit SVG, ambient grid, teal-green glows, small-screen spacing, HUD glass panels, active navigation illumination, mobile-friendly performance with a reduced-motion override.

The feed shows only the signed-in user's actual recorded reward activity (device-local for preview users). It never fabricates trades, token prices, investment returns, live blockchain status or user transactions.

**Update delivery:** Commit changes in GitHub to trigger Vercel Git integrations. If the website still shows the old version, check the crypto project's most recent Vercel build status, then reload the app.



## Telegram bot setup — before the database

ZENQORY has a FastAPI Telegram webhook at POST /api/telegram/webhook; it answers /start, /app, /help and /status with an inline **Launch ZENQORY** Mini App button. It also supports other text with a simple navigation response. The bot handler does not depend on PostgreSQL.

**Required owner-only Vercel step:** Add a sensitive production environment variable BOT_TOKEN (from BotFather) in Vercel → crypto → Settings → Environment Variables. **Never put the token in GitHub, chat, public URLs or screenshots.** Redeploy production after adding it.

In BotFather, configure /setmenubutton on the bot with URL https://crypto-jade-nine.vercel.app and title "Open ZENQORY". Open the Mini App **from the Telegram bot chat** once. The frontend sends the signed Telegram initData to POST /api/telegram/activate; the server verifies the Telegram HMAC using BOT_TOKEN, registers the fixed HTTPS webhook with a derived secret, and sets menu button and commands. This is automatic after token setup, no manual API URL with the token needed.

Once the Mini App has opened from Telegram, send /start again in the bot chat to see the welcome and Launch button. The profile's "Launch App" and bot-menu appearance are Telegram/BotFather settings, not only website settings.

Public, non-secret diagnostic endpoint: GET /api/telegram/status. It reports whether BOT_TOKEN is configured, without showing any credential. If BOT_TOKEN is missing, Telegram bot replies cannot activate; the website still works in local preview mode without a database. Preview points are device-local, not actual server balances.

**Security:** Telegram webhook requests require the correct X-Telegram-Bot-Api-Secret-Token. The activation endpoint requires cryptographically verified Telegram Mini App initData, and registers only the fixed ZENQORY domain. Live reward APIs still require signed identities and PostgreSQL.

## Telegram intro media and Join Channel

Telegram's bot description supports animation through @BotFather > /mybots > ZENQORY > Edit Bot > Edit Description Picture. Upload the delivered ZENQORY_Bot_Description.gif (320x180 looping GIF) or ZENQORY_Telegram_Intro.mp4 (640x360 video). Uploading description media requires the owner to use BotFather, and is not done automatically by GitHub or the webhook. The concise English welcome copy synchronizes via GET /api/telegram/status.

The /start, /app, /help, /status and /channel bot messages display a second inline button labelled Join Channel below Launch ZENQORY when the official community URL is known. In Vercel project crypto, set environment variable CHANNEL_URL (Production) to the real https://t.me/channel_username or a real private invite URL, then redeploy. The link is validated and does not fall back to a fabricated channel. Without CHANNEL_URL, launch works normally and /channel says the link is pending. CHANNEL_URL is NOT BOT_USERNAME.


## Verified Missions & Referral Mining Boost (Genesis v1.3)

### Rewards rules, enforced by the server

- A farming cycle lasts **8 hours**, and the base reward is **80 ZNQY points**.
- Each friend who signs up through the inviter's **personal Telegram referral link** and completes a real first farming claim becomes an active referral.
- Each **active** referral adds **+2%** to the inviter's *future* farming rewards, capped at **+20%** (10 active referrals). Rounded whole-point examples: 0 → 80; 1 → 82; 3 → 85; 5 → 88; 10+ → 96 points per cycle.
- The boosted payout is **calculated on the server and locked in the database at farm start**. Existing active cycles from before this version retain their originally earned 80-point payout. New referrals never retroactively modify a running cycle.
- Inviter still receives the existing **+10 one-time referral bonus** after the invitee's first successful real farming claim. The bonus and mining boost are separate rewards.
- **No mission reward is allowed just for tapping CLAIM.** The API checks real database facts before awarding points. Current missions retain their original stable IDs and once-only payouts (including grandfathered claims from earlier versions):
  - `welcome` +30: Start a real farming cycle.
  - `safety` +20: Complete and claim the first real farming cycle.
  - `profile` +15: Invite a friend who completes the first real farming claim.
- **When creating future missions:** first define and test a *server-verifiable* completion condition (such as a persisted farm cycle, referral activation or securely verified external service action). Only then add the task to the UI and reward allowlist. Never award rewards based solely on client-side clicks, localStorage, unverified URLs or user assertions.
- Double payouts are blocked by PostgreSQL transactions, locked user rows and the unique `zen_tasks(user_id,task_id)` constraint. Browser demo balances are not real server rewards.
- Frontend refreshes personal referral/boost stats on Friends, Home and Earn navigation, and when Telegram becomes visible (throttled to avoid excess database requests).

### Verification before scaling

CI runs Telegram auth and transactional PostgreSQL integration tests against an **isolated** disposable `zenqory_test` database. Destructive test operations explicitly refuse non-local / production Neon URLs.

Production acceptance still requires one independent, real two-account Telegram invitation test and one full eight-hour claim, plus a passing GitHub Actions run. A Vercel `READY` build is not itself evidence of that end-to-end acceptance.
