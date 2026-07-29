# Runtime Proof Sequence

## Identity

- Environment and time window
- Tenant, office, client, document, job, and request identifiers
- Expected and observed state

## Code path

- Rendering component and mapper
- Request contract and route
- Service/workflow decision
- Persistence write and read

## Runtime path

- Relevant `workflow_records` event chain
- Worker lease, attempts, status, timings, and error
- Provider request category and response status without secrets
- Application, proxy, and container evidence when relevant

## Conclusion

- Confirmed cause
- Contributing factors
- Disproved hypotheses
- Missing evidence
- Narrow fix and regression scope, only when implementation is requested
