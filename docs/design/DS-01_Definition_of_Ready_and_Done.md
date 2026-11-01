# DS-01: Definition of Ready and Definition of Done

Status: draft for team review, 1 Nov 2026.

## Definition of Ready

A story can enter a sprint when all of these are true:

- It has a user story, an owner, story points and a sprint.
- Its acceptance criteria can be tested and it traces to an FR, NFR or metric.
- API changes are in `docs/design/openapi.yaml`, and data changes are in Database Design v1.3 or later.
- Stories it depends on are done or planned earlier in the same sprint.
- Business values it needs, such as thresholds, are agreed by the Product Owner.

## Definition of Done

A story is done when all of these are true:

- All acceptance criteria are met and shown to another team member.
- The code is merged to `main` through a pull request reviewed by at least one other member.
- Unit and API tests cover the main, alternative and exception flows, and all tests pass.
- Responses match the OpenAPI contract, including reason codes, and 401/403 are tested.
- Stock, sync and decision changes write to `audit_log` where the story requires it.
- Schema changes are new forward-only migrations that run on a clean database.
- No secret, `.env`, `bin/` or `obj/` file is committed.
- The README or design document is updated if behaviour or setup changed.
- The sprint backlog shows the status and actual hours.

A sprint is done when its stories are done, the integrated build runs with Docker Compose, the demo has been shown, and the retrospective notes are recorded.
