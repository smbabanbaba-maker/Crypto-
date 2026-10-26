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
