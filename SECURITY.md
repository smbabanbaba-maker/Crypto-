# ZENQORY security and launch runbook

ZENQORY records **off-chain, pre-launch community points**; they are not cryptocurrencies, money, or a token-issuance promise.

## Authentication and access control

- Reward APIs require **Telegram Mini App signed `initData`**, validated server-side with the bot-token HMAC, including Telegram's modern `signature` field when present.
- The verified Telegram user ID (not a client-provided ID) determines which PostgreSQL user is read or modified.
- No public transaction, balance mutation, or withdrawal endpoints exist.
- Telegram webhook updates require a constant-time comparison of the bot's derived secret header.
- Bot webhooks and menu settings may be modified only by a Telegram account whose numeric ID matches the **optional** `ZENQORY_ADMIN_TELEGRAM_ID` production environment variable. If unset, this administrative API rejects everyone. Do not expose this value in public UI.
- Database and bot diagnostic routes require signed Telegram `initData` and intentionally respond 401 to unsigned browser requests.
- The normal browser supports **local demonstration only**; it cannot send demo rewards to the server. Telegram login/database failures disable secure reward actions and show a retry option in Profile.

## Referral rules

- The personal **Main Mini App** invite is `https://t.me/<official-bot>?startapp=ref_<verified-user-id>`.
- The fallback **Telegram chat** invite is `https://t.me/<official-bot>?start=ref_<verified-user-id>`. When a new person presses Start, the authenticated bot webhook stores a pending invite for up to seven days. Opening the Mini App then attributes the person to their inviter.
- Both are signed/validated at the server. A user cannot refer themselves.
- A previously registered user cannot switch inviters by opening a new link; the first accepted invite controls attribution.
- New invited accounts are counted at registration. An **active** invited account has at least one finished farming cycle.
- Referrers receive +10 ZNQY points **once**, only after their invitee finishes and claims their first 8-hour farming cycle, all inside a PostgreSQL transaction.
- Genuine multiple Telegram accounts are not equivalent to unique real-world humans; launch monitoring and anti-Sybil review are still required at scale.

## Reward integrity

- Farm starts and claims lock the user's row (`SELECT ... FOR UPDATE`) and reject duplicated or premature actions with 409.
- Daily rewards are enforced server-side with a 24-hour minimum interval and a row lock.
- Single-use missions have a compound PostgreSQL primary key; duplicate reward claims are rejected.
- User balance, points ledger and referral bonus updates occur in a single database transaction.
- The server sets all timestamps/reward amounts: a modified client clock, localStorage value or replayed button click cannot accelerate a real claim.

## HTTP and deployment

- Vercel serves HTTPS, anti-sniff and restrictive Content Security Policy headers. Fonts and Telegram's official WebApp bridge are explicitly allowed.
- Database and bot credentials reside in **Vercel Sensitive Environment Variables**, never inside the GitHub repository or frontend JavaScript.
- API responses opt out of caching. Browser content can still be rendered when an authorization failure occurs, but no API points are awarded.
- Bot status and database status were previously publicly accessible for setup; they now require Telegram authentication.
- Automated CI workflow: `.github/workflows/zenqory-security.yml` tests auth, bot webhooks, first-invite/referral attribution, duplicate rewards, concurrency, and database connectivity using a **disposable PostgreSQL container**. Never connect test runners to production Neon.
- Do not enable monetary purchases, wallets, payments or token exchange until independent security and legal reviews.

## Final manual end-to-end checks (required before mass invites)

1. From the official Telegram bot, open ZENQORY as an existing account. Ensure **Profile → Account** confirms verified storage, and there is no Local Demo Points indicator.
2. Close/reopen Telegram Mini App. Real balance and prior reward history must persist.
3. Copy **Invite Friends** from account A; open the direct Mini App invite on a *new*, distinct Telegram account B. B must appear in A's Invited count, not Active yet.
4. Repeat with the alternate **Share Bot Invite Link** on new account C; press /start then Launch. C must be attributed to A.
5. On account B, start farming; verify an immediate claim fails. After eight real hours, claim once. A must receive only +10 points and Active count increases by one. Second claim must fail.
6. Claim a daily reward twice quickly. The first may succeed; the second must not award anything.
7. Verify self-referral and use of referral links by an already-registered account do not create duplicate invite credits.
8. Open the link outside Telegram: only explicitly labeled device-local demo points should be available.
9. Test mobile scrolling across all five tabs, bottom navigation remaining fixed, share/copy buttons, and channel link.
10. Review Vercel function logs, firewall request patterns and Neon usage after a small invited beta before large-scale promotion.

**Security is defense-in-depth, not a promise of absolute immunity.** Monitor abuse, keep dependencies current, maintain database backups, and rotate BotFather tokens promptly if ever exposed.
