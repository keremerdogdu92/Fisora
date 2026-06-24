# Production Container Restart Design

## Goal

Keep the Fisora production stack available after a host reboot without manually
starting Docker Compose services.

## Design

Set `restart: unless-stopped` on every long-running production service:
`postgres`, `redis`, `backend`, `worker`, `frontend`, `nginx`, and `backup`.
Leave `migrate` without a restart policy because it is a one-shot service that
must complete before the backend starts.

Apply the same policy to the currently existing server containers before
starting them, so the live outage is recovered without recreating containers or
changing secrets. Future Compose deployments will preserve the policy from the
repository configuration.

## Verification

- A regression test checks the policy for all long-running services and checks
  that `migrate` remains excluded.
- `docker compose config` validates the production Compose file.
- Live verification checks container health, Docker restart policies,
  `/health`, readiness, and the public HTTP route.
