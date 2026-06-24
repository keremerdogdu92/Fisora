# Production Container Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the Fisora production stack and make long-running services restart automatically after host reboots.

**Architecture:** Docker remains managed by the existing production Compose project. Long-running services use `unless-stopped`; the one-shot migration service remains excluded. Existing live containers receive the same policy before they are started.

**Tech Stack:** Docker Compose, Python unittest, PowerShell, SSH

---

### Task 1: Add restart-policy regression coverage

**Files:**
- Create: `backend/tests/test_production_restart_policy.py`

- [ ] **Step 1: Write the failing test**

Read `docker-compose.production.yml`, locate each top-level service block, and
assert that long-running services contain `restart: unless-stopped` while
`migrate` does not.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest backend.tests.test_production_restart_policy
```

Expected: FAIL because the production services do not yet declare a restart
policy.

### Task 2: Add the production restart policy

**Files:**
- Modify: `docker-compose.production.yml`

- [ ] **Step 1: Add `restart: unless-stopped`**

Add the policy to `postgres`, `redis`, `backend`, `worker`, `frontend`, `nginx`,
and `backup`. Do not add it to `migrate`.

- [ ] **Step 2: Run focused verification**

Run:

```powershell
python -m unittest backend.tests.test_production_restart_policy
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml config --quiet
git diff --check
```

Expected: all commands exit successfully.

### Task 3: Publish and recover production

**Files:**
- Modify: live Docker container metadata on `185.184.208.188`

- [ ] **Step 1: Commit and push the tested repository change**

Commit only the restart-policy spec, plan, test, and Compose file, then push
`main` without including unrelated untracked files.

- [ ] **Step 2: Apply policy to existing containers**

Use `docker update --restart unless-stopped` for the seven long-running Fisora
containers and start them. This avoids recreation and preserves the current live
environment.

- [ ] **Step 3: Verify production**

Check that all seven containers are running or healthy, their restart policy is
`unless-stopped`, `/health` returns 200, readiness reports `ready=true` and
`pilot_sellable=true`, and the public root route returns 200.
