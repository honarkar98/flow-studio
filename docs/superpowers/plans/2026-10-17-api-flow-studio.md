# API Flow Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, project-agnostic local web app for importing Swagger/OpenAPI, composing persistent variable-driven HTTP flows, and running/resuming them with a full exchange timeline; ship an editable CLM v2 example.

**Architecture:** Python standard-library HTTP server serves a small RTL web UI and JSON API. SQLite stores projects, operations, flows, variables, runs, and exchanges. A schema module, expression module, and runner have separate interfaces; the CLM preset only supplies data to the generic engine.

**Tech Stack:** Python 3.12+, SQLite, `http.server`, `urllib.request`, PyYAML 6.0.3, vanilla HTML/CSS/JavaScript, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-17-api-flow-studio-design.md`

## Global Constraints

- `api-flow-studio/` is independent of both CLM repositories and has no runtime import from them.
- Bind the tool to `127.0.0.1`; default tool port `8765`; target base URL is per project.
- Preserve project flows, variables, runs, exchanges and missing operations on schema reimport.
- Show URL, method, request JSON, response JSON, status and time in execution order; mask sensitive values by default.
- Never print OTP, national ID, token, or raw response payloads to server logs.
- The CLM preset is editable data; all core components work with other Swagger 2.0 and OpenAPI 3.x APIs.

## Review Focus

1. Empty tenant/array capture must fail visibly without overwriting an old variable — Task 2 test.
2. Reimport with a removed or renamed operation must retain the flow and flag the old operation — Task 1 test.
3. Rerunning a successful POST must require an explicit duplicate-action acknowledgement — Task 3 and Task 5 tests.
4. A timed-out request or crash must not silently advance the checkpoint — Task 3 test.
5. A 401 refresh failure must preserve unrelated variables and record both HTTP attempts — Task 3 test.

---

### Task 1: Project storage and schema catalogue

**Files:** Create `studio/store.py`, `studio/schema.py`, `studio/__init__.py`, `requirements.txt`, `.gitignore`; Test `tests/test_store_schema.py`.

**Interfaces:** `Store(path)` with `create_project(name, base_url)`, `list_projects()`, `get_project(id)`, `save_project(id, changes)`, `save_flow(project_id, flow)`, `get_flow(id)`, `list_flows(project_id)`, `set_variable(project_id, name, value, sensitive=False)`, `get_variables(project_id)`, `import_schema(project_id, text) -> diff`; `schema.parse(text) -> (version, operations)`.

- [ ] Write failing tests for two isolated projects, Swagger 2.0/OpenAPI 3.x parsing, and reimport that retains an absent operation with `missing=True` while preserving flow and variables.
- [ ] Run `python -m unittest tests.test_store_schema -v`; verify failure is missing behavior.
- [ ] Implement SQLite migrations and safe YAML parser; store operation IDs by `(project_id, method, path)` and update/mark missing in one transaction.
- [ ] Run the targeted tests and `python -m unittest discover -s tests -v`; verify pass.
- [ ] Commit `feat: store projects and import OpenAPI catalogues`.

### Task 2: Variable rendering, capture and request preview

**Files:** Create `studio/expressions.py`, `studio/request.py`; Test `tests/test_expressions.py`.

**Interfaces:** `render(value, variables) -> JSON value`; `extract(document, path) -> JSON value`; `build_request(project, step, variables) -> PreparedRequest(method, url, headers, body, content_type)`; `capture(response_json, rules, variables) -> dict` without mutating input; `assert_response(response_json, rules)`.

- [ ] Write failing tests for typed exact placeholders, embedded placeholders, URL/path/query encoding, nested and array extraction, empty-array failure, multipart field/file preparation, and response assertions.
- [ ] Run `python -m unittest tests.test_expressions -v`; verify red for the missing functions.
- [ ] Implement pure rendering/capture and request construction with explicit errors for missing variables and paths.
- [ ] Run targeted tests and the suite; verify pass.
- [ ] Commit `feat: render variables and map HTTP payloads`.

### Task 3: Persistent step runner and exchange history

**Files:** Create `studio/runner.py`, `studio/transport.py`; extend `studio/store.py`; Test `tests/test_runner.py`.

**Interfaces:** `Runner(store, transport).start(flow_id, start_index=0, acknowledge_post=False) -> run_id`; `.advance(run_id, manual_values=None, acknowledge_post=False) -> run_state`; `.preview(flow_id, step_index) -> dict`; transport callable `send(PreparedRequest) -> HTTPResult` injected for tests. Store methods persist run cursor/status and append ordered exchange records atomically with captured variables.

- [ ] Write failing tests for OTP/manual pause, resume after new Store instance, starting at contract step with saved variables, non-2xx/timeout checkpoints, explicit POST rerun acknowledgement, configured token refresh and 401 failure, and ordered full exchange JSON.
- [ ] Run `python -m unittest tests.test_runner -v`; verify red.
- [ ] Implement runner state machine and `urllib.request` transport; log each HTTP attempt, including refresh and retry; store no raw payload in console logs.
- [ ] Run targeted tests and the suite; verify pass.
- [ ] Commit `feat: execute and resume persistent flows`.

### Task 4: Editable CLM example flow

**Files:** Create `studio/presets.py`; Test `tests/test_clm_preset.py`.

**Interfaces:** `install_clm_v2_preset(store, project_id) -> flow_id`; produces ordinary editable steps and generic refresh settings, with no runner or parser special cases.

- [ ] Write failing tests that resolve all preset operations against the live-schema fixture shape, verify 12 ordered steps and captures/assertions, and confirm installation in a non-CLM project does not affect the engine.
- [ ] Run `python -m unittest tests.test_clm_preset -v`; verify red.
- [ ] Implement the preset as data with a simple TipTap/HTML content default, manual signer variable, first-tenant capture, and final `contract.status=signing` assertion.
- [ ] Run targeted tests and the suite; verify pass.
- [ ] Commit `feat: include editable CLM v2 contract flow`.

### Task 5: Local JSON API and RTL browser editor

**Files:** Create `studio/server.py`, `studio/__main__.py`, `web/index.html`, `web/app.js`, `web/style.css`; Test `tests/test_server.py`.

**Interfaces:** JSON API for projects/schema/operations/flows/variables/runs/exchanges, import by text or URL, flow step CRUD and reorder, preview/start/continue/retry, and file upload. UI uses these routes for project selector, endpoint catalogue, step editor, variable vault, run controls, and ordered timeline.

- [ ] Write failing handler tests for CRUD, reimport diff, missing-variable preview, manual advance, duplicate POST acknowledgement, safe local file upload, and masked-by-default exchange serialization.
- [ ] Run `python -m unittest tests.test_server -v`; verify red.
- [ ] Implement API and static UI with Persian labels and RTL; make sensitive fields revealable only on deliberate UI action.
- [ ] Run targeted tests and the suite; verify pass.
- [ ] Commit `feat: add local web flow editor and execution timeline`.

### Task 6: Usability, live schema check and delivery

**Files:** Create `README.fa.md`, `tests/test_end_to_end.py`; update any files above only for observed failures.

**Interfaces:** `python -m studio --host 127.0.0.1 --port 8765 --db data/studio.sqlite3`; README documents separate virtualenv, schema import, variables, resume and CLM example.

- [ ] Write failing end-to-end test using a fake transport for a generic flow: import → configure → pause → resume after restart → inspect ordered requests/responses.
- [ ] Run `python -m unittest tests.test_end_to_end -v`; verify red.
- [ ] Finish startup/docs and fix only failures exposed by the test.
- [ ] Run `python -m unittest discover -s tests -v`, `python -m compileall -q studio`, `git diff --check`, and browser smoke on `127.0.0.1:8765`; verify output.
- [ ] Import the live schema from `127.0.0.1:8000`, validate every CLM preset method/path, then attempt live flow only with supplied test identity, OTP, and signer ID. Record exact completed stage and any unavailable dependency.
- [ ] Commit `docs: document startup and verify complete flow`.
