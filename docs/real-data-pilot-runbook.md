# Real Data Restricted Pilot Runbook

This runbook is the gate for letting an accountant test Fisora with real invoice and bank/POS statement data.

## Required Server Posture

- Deploy the latest `main` branch to the restricted live server.
- Use PostgreSQL as the active store: `FISORA_STORE_BACKEND=postgres`.
- Require application sessions: `FISORA_AUTH_MODE=session_required`.
- Keep secure session cookies enabled: `FISORA_SESSION_COOKIE_SECURE=true`.
- Keep password bootstrap disabled after setup.
- Keep backup, document storage, export storage, AI provider, and rate limits healthy.
- Restrict access with TLS, VPN, IP allowlist, or a private network.

Minimum real-data pilot env:

```env
FISORA_REAL_DATA_PILOT_ENABLED=true
FISORA_REAL_DATA_ACCESS_MODE=restricted_network
FISORA_AUTH_MODE=session_required
FISORA_SESSION_COOKIE_SECURE=true
FISORA_STORE_BACKEND=postgres
```

`FISORA_REAL_DATA_ACCESS_MODE` accepts `tls`, `restricted_network`, `vpn`, or `ip_allowlist`.

## Gate Commands

From the live checkout:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
sh deploy/scripts/fisora-prod.sh check
sh deploy/scripts/fisora-prod.sh deploy
sh deploy/scripts/fisora-prod.sh smoke
```

From Windows or a workstation with HTTP access:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-health.ps1 `
  -BaseUrl https://YOUR_RESTRICTED_HOST `
  -RequireRealDataPilot
```

The gate is closed if `real_data_pilot.allowed` is `false`. Do not upload accountant-owned real documents until that value is `true`.

## First Accountant Flow

1. Log in as the accountant.
2. Create or select one taxpayer.
3. Upload one invoice/e-invoice file and one bank/POS statement file.
4. Wait for worker processing to finish.
5. Review AI/rule draft, deterministic balance status, and export gate reason.
6. Save at least one accountant decision or correction.
7. Confirm learning/audit event exists through the operation health view.
8. Generate the controlled CSV/manifest export package.

The export must be described as a controlled candidate package until the accountant verifies the import format inside Zirve.
