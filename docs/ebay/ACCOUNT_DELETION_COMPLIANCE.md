# eBay Marketplace Account Deletion / Closure Notification compliance

ARIE persists eBay listing and seller-related data. The **exemption for
applications that do not store eBay user data does not apply**. Do not tick
that exemption in the Developer Portal.

Official first-party sources (verify on developer.ebay.com if the portal
copy has moved):

- Marketplace Account Deletion:
  https://developer.ebay.com/marketplace-account-deletion
- Notification API public-key:
  `GET https://api.ebay.com/commerce/notification/v1/public_key/{public_key_id}`
- Official Event Notification SDKs (Apache-2.0; no official Python SDK):
  - https://github.com/eBay/event-notification-nodejs-sdk
  - https://github.com/eBay/event-notification-java-sdk
  - https://github.com/eBay/event-notification-golang-sdk
- Topic: `MARKETPLACE_ACCOUNT_DELETION`
- Signature header: `X-EBAY-SIGNATURE` (Base64 JSON `{kid, signature}`)
- Algorithm: ECDSA with SHA-1 over the raw POST body (Node SDK `ssl3-sha1`)
- Challenge: SHA-256(`challengeCode` + `verificationToken` + `endpoint`) as
  lowercase hex JSON `{"challengeResponse": "..."}`
- Verification token: 32–80 characters, `[A-Za-z0-9_-]`
- Endpoint: public HTTPS, no auth, no redirect
- Acknowledge valid notifications with **204** quickly. Return **412** for
  an invalid signature. Return **500** on internal/key-fetch failure so eBay
  retries. Do not return 2xx if deletion has not been persisted.

## Why the Production keyset is disabled

eBay disables Production API keysets until Marketplace Account Deletion
notifications are configured. A Production OAuth `401 invalid_client` in
that state is **not** a wrong Client ID/Secret. Do not regenerate keys.

## Public endpoint (permanent)

Do **not** use ngrok or any other tunnel as the permanent endpoint.

The webhook is part of this FastAPI app:

```
GET/POST https://<your-https-host>/webhooks/ebay/account-deletion
```

Permanent hosting: the same Docker/Caddy/nginx stack already in this repo,
with a stable hostname and TLS. Do not buy a new paid host without
authorising that spend.

Local-only ARIE cannot receive eBay's challenge. Either:

1. Deploy this app (or a copy that shares `DATABASE_URL`) behind HTTPS, or
2. Temporarily expose the existing process only long enough to pass the
   GET challenge, then keep that same HTTPS URL online so eBay can POST.

The GET challenge does **not** need OAuth. Signature verification on POST
**does** need Production client-credentials to fetch eBay public keys. That
works after the keyset is enabled.

## Owner actions in the eBay Developer Portal

Do this **after** the HTTPS URL is live and
`EBAY_NOTIFICATION_VERIFICATION_TOKEN` is in `.env` (never commit it).

Generate a token if needed:

```bash
make ebay-notification-token
```

Confirm readiness (does **not** claim eBay subscription is active):

```bash
make ebay-notification-check
```

Then, in the Developer Portal:

1. Open the application whose **Production** keyset is disabled.
2. Open **Alerts & Notifications** (wording may be **Notifications** /
   **Marketplace Account Deletion**).
3. Select topic **`MARKETPLACE_ACCOUNT_DELETION`**.
4. Notification Endpoint URL (exactly, HTTPS, no trailing slash unless that
   is how the server is mounted):

   `https://<your-https-host>/webhooks/ebay/account-deletion`

   That value must equal `EBAY_NOTIFICATION_ENDPOINT_URL` in `.env`.
5. Paste **Verification Token** from `.env` key
   `EBAY_NOTIFICATION_VERIFICATION_TOKEN`. Do not put the token in git,
   docs, or chat logs.
6. Enter the destination **email** eBay should use for notification
   problems (your operator email).
7. Save / verify / subscribe. eBay will GET the endpoint with
   `challenge_code`. ARIE must return HTTP 200 and JSON
   `challengeResponse`.
8. Confirm the Production keyset shows **enabled**.
9. Then run:

```bash
make ebay-check
```

Expected only **after** the keyset is enabled:

- `POST https://api.ebay.com/identity/v1/oauth2/token` → 200
- Browse Production → 200
- `real listings > 0` when the query matches live inventory
- `sandbox_used=false`

Until the dashboard shows the keyset enabled, Production OAuth may still
return `401 invalid_client`. That is the disabled-keyset state, not a cue
to rotate credentials.

## Configuration (`.env` only)

```
EBAY_NOTIFICATION_VERIFICATION_TOKEN=<32-80 chars, A-Za-z0-9_->
EBAY_NOTIFICATION_ENDPOINT_URL=https://<your-https-host>/webhooks/ebay/account-deletion
```

Health:

- `GET /health/ebay-notifications`
- `make ebay-notification-check`

`ebay_subscription_active` stays `false` until you confirm the portal
subscription yourself. ARIE cannot see the Developer Portal.

## Deletion behaviour

Identifiers in the event (`username`, `userId`, `eiasToken`) are hashed
and matched to listings. Matching eBay marketplace rows are deleted.
Purchases, sales, owner_sales, and paper trades keep amounts/dates and
redact notes (`ACCOUNTANT_REQUIRED` / `LEGAL_CONFIRMATION_REQUIRED`).
Audit events drop payload bodies. The deletion audit stores hashes and
counts only — not the username.

Processing is idempotent on `notificationId`. Invalid signatures never
delete data.
