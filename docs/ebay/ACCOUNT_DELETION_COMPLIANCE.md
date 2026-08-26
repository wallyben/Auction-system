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

## Activate (agent + one portal Save)

```bash
make ebay-notification-activate
make ebay-notification-watch
```

Owner paste sheet (exact URL + token command + click sequence):

`docs/ebay/OWNER_PORTAL_ACTION.md` and `artifacts/ebay_owner_portal_action.txt`

Retrieve the token only when you are pasting it:

```bash
make ebay-notification-show-token
```

If a persistent HTTPS host is added later:

```bash
make ebay-notification-set-endpoint URL=https://<host>/webhooks/ebay/account-deletion
make ebay-notification-proof
```

Do not tick the exemption. Do not regenerate Production keys.

After Save, the agent polls Production OAuth with `make ebay-notification-await`.

## Configuration (`.env` only)

```
EBAY_NOTIFICATION_VERIFICATION_TOKEN=<32-80 chars, A-Z a-z 0-9 _ ->
EBAY_NOTIFICATION_ENDPOINT_URL=https://<your-https-host>/webhooks/ebay/account-deletion
```

Health:

- `GET /health/ebay-notifications`
- `make ebay-notification-check`

`ebay_subscription_active` stays `false` until the portal subscription is confirmed.

Expected only **after** the keyset is enabled:

- `POST https://api.ebay.com/identity/v1/oauth2/token` → 200
- Browse Production → 200
- `real listings > 0` when the query matches live inventory
- `sandbox_used=false`

Until the dashboard shows the keyset enabled, Production OAuth may still
return `401 invalid_client`. That is the disabled-keyset state, not a cue
to rotate credentials.

## Deletion behaviour

Identifiers in the event (`username`, `userId`, `eiasToken`) are hashed
and matched to listings. Matching eBay marketplace rows are deleted.
Purchases, sales, owner_sales, and paper trades keep amounts/dates and
redact notes (`ACCOUNTANT_REQUIRED` / `LEGAL_CONFIRMATION_REQUIRED`).
Audit events drop payload bodies. The deletion audit stores hashes and
counts only — not the username.

Processing is idempotent on `notificationId`. Invalid signatures never
delete data.
