# eBay portal — only remaining owner action

```
ENDPOINT URL:
NOT SET — deploy ARIE on a persistent HTTPS host, then: make ebay-notification-set-endpoint URL=https://<host>/webhooks/ebay/account-deletion

VERIFICATION TOKEN:
make ebay-notification-show-token

TOPIC:
MARKETPLACE_ACCOUNT_DELETION

OPERATOR EMAIL:
walshe.ben@gmail.com

CLICK SEQUENCE:
1. Open https://developer.ebay.com/my/keys and sign in (MFA if asked).
2. Open the Production application whose keyset is disabled.
3. Alerts & Notifications → Marketplace Account Deletion.
4. Paste Endpoint URL (exact string above).
5. Paste token from `make ebay-notification-show-token`.
6. Enter operator email.
7. Save. Leave `make ebay-notification-watch` running to see:
   EBAY_CHALLENGE_RECEIVED
   EBAY_CHALLENGE_RESPONDED_200
   EBAY_NOTIFICATION_ENDPOINT_VERIFIED
8. Do not tick the 'we do not persist eBay user data' exemption.

AUTOMATION_STATUS: EBAY_COMPLIANCE_BLOCKED_EXTERNAL
```
