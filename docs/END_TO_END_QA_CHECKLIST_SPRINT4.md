# End-to-End QA Checklist - Sprint 4

Status legend:
- PASS = behavior validated
- FAIL = behavior not validated
- BLOCKED = could not validate due to environment/tooling limitation

## Scope
This checklist validates Sprint 4 multi-project security flow:
- Login and session creation
- Project authorization per user
- Admin-only controls
- Project creation and assignment workflows
- Validation tab readiness based on selected project

## Test Data (Demo Users)
- admin_user
- validator_demo
- validator_other

Expected access matrix:
- admin_user -> kenya-2024 (admin), nairobi-2023 (admin)
- validator_demo -> demo-project (validator), kenya-2024 (validator)
- validator_other -> nairobi-2023 (validator)

## E2E Cases

| ID | Area | Precondition | Steps | Expected Result | Status |
|---|---|---|---|---|---|
| E2E-01 | App bootstrap | Virtual env active | Start app and open local URL | App starts without runtime exception | PASS |
| E2E-02 | Login | App running | Login as admin_user | Session is created and user is authenticated | PASS |
| E2E-03 | Project selector | admin_user logged in | Open Select Project tab | Authorized projects are listed (kenya-2024, nairobi-2023) | PASS |
| E2E-04 | Validation readiness | admin_user logged in | Open Validation tab | Validation status is ready with selected project | PASS |
| E2E-05 | Admin visibility | validator_demo logged in | Open Admin tab | Access denied message and hidden admin controls | PASS |
| E2E-06 | Admin visibility | admin_user logged in | Open Admin tab | Admin controls are visible | PASS |
| E2E-07 | Project creation | admin_user logged in | Create project with slug/name/repo_id | New project is created and project list is refreshed | PASS |
| E2E-08 | Project assignment | admin_user logged in | Assign user to a project | Assignment succeeds and access matrix updates | PASS |
| E2E-09 | Non-admin write protection | validator_demo logged in | Attempt assignment/create actions | Actions are denied by backend callback checks | PASS |
| E2E-10 | ACL isolation | Test suite available | Run ACL tests | ACL tests pass (project isolation enforced) | PASS |

## Execution Notes
- This checklist is aligned with fixes applied in src/ui/app_factory.py.
- The app uses Gradio and callback-driven state transitions.
- ACL behavior is also covered by unit tests in tests/unit/test_acl_enforcement.py.

## Evidence Commands
1. python -m pytest tests/unit/test_acl_enforcement.py -q
2. python -m pytest -q --tb=line
3. Start app on a free port and verify local HTTP response

## Sign-off
- Sprint 4 E2E status: PASS
- Date: 2026-03-25
