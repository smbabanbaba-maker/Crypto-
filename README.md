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
