> **Status (2026-10-25):** survey snapshot. Since written: the upstreamable fixes landed in this fork as PRs #1–#7 (release workflow, image-tag docs, #29 message, multi-key fleet tools, host name/MAC + site slug resolution, tool annotations, `list_traffic_flows`); the fork-identity changes ship in the `fork/release-identity` PR. Open follow-up: the connector relay still redacts credential fields in response bodies (`tools/connector.py`), contrary to the pass-through invariant.

# Fork triage: elliotmatson/unifi-fabric-mcp-server

Survey date: 2026-10-25. Upstream: `swkstudios/unifi-fabric-mcp-server`. Fork baseline:
`main` = upstream `main` = `5c08c09` (Release v0.6.2), so there's no divergence yet.

Data sources: git (upstream and other forks fetched read-only into `refs/forks/*`) and
the public GitHub web pages. The GitHub API for upstream wasn't available in this session
(credentialed attach was refused), so the issue, PR, and fork listings come from the
rendered pages. Issue bodies are summaries of those pages, not verbatim copies.

## 1. Upstream health

Upstream is a release mirror, not an active development repo. Its whole history on
`main` is three squashed "Release vX.Y.Z" commits. The last one, **v0.6.2, landed
2026-08-17 (about 10 weeks ago)**. Tags: v0.3.10, v0.3.11, v0.3.14, v0.3.153–155,
v0.6.0, v0.6.2. **There's no `v0.6.1` tag**, although the README pins
`ghcr.io/swkstudios/...:0.6.1` everywhere and `pyproject.toml` says `0.6.2`. There's
also no PyPI package (issue #23). Issues: **7 open / 11 closed**. All 7 open issues were
filed by the maintainer account (`TeknoCentral`) on release day as a roadmap, and none
has a reply. PRs: **0 open / 11 closed** (4 merged: two bot release PRs, #11, #3). There
are no maintainer status notes. Repo files still mention an internal `dev` branch and a
"content-scan battery in the publish workflow" that doesn't exist in the public tree,
which suggests the real development happens privately and is mirrored out. Nothing has
moved since August, which supports treating it as unmaintained.

Baseline on this fork (unchanged `main`): ruff check / ruff format / mypy / gen_tools_doc
`--check` all pass; **pytest 1524 passed, 81 skipped, coverage 92.62%** (gate is 91%).
Runtime: **283 tools, 0 annotated**, FastMCP 3.4.11 installed (pin `>=3.2,<3.5`).
Note: in this container the `pytest` on PATH is an isolated uv tool, so use
`python3 -m pytest`.

## 2. Open upstream issues

| # | Title | Type | Still applies to `main`? | Severity | Proposed action |
|---|---|---|---|---|---|
| 29 | Connector write relay ships disabled by default with an unactionable error message | Feature / UX (security-relevant) | **Yes.** `config.py:322` defaults `enable_connector_write` off; refusal text at `tools/connector.py:375` only says "set UNIFI_ENABLE_CONNECTOR_WRITE=1 in the server environment". | Low | **Partial.** Improve the refusal message and document where to set the flag. **Keep the default off.** Flipping it would loosen a write guard on a raw relay (`fabric_connector_*` can hit any console endpoint), and with annotations a gateway can already separate these. Optional small fix PR. |
| 28 | Dry-run preview and optional audit log for write operations | Feature | Yes (nothing exists) | Low | **Defer.** The audit log as proposed (append-only JSONL file) conflicts with the repo's stateless / no-file-logging rule. If wanted, log to stdout or do it in the gateway. Dry-run is a large cross-cutting change. |
| 27 | Reduce advertised tool count: family selection and/or lazy registration | Feature | Yes (283 tools registered eagerly) | Low/Med (client context cost) | **Defer.** Phase 4 annotations let gateways and clients filter reads from writes, which covers part of this. Family env flags could follow later. |
| 26 | Optional credential redaction mode (opt-in, default off) | Feature (security-adjacent) | Yes (no such mode) | n/a | **Skip.** Breaks the pass-through invariant (CLAUDE.md, CONTRIBUTING.md, and the CI "No runtime response redaction" grep). Masking belongs in the deployment, e.g. your MCP gateway. |
| 25 | Add UniFi Access tool coverage (blocked: no official Fabric API) | Feature, **blocked/stale** | Blocked on Ubiquiti publishing an Access API | n/a | **Skip.** You already run a separate UniFi Access MCP server. |
| 24 | Homebrew formula | Feature | Yes | n/a | **Skip.** Not needed for a gateway/container deployment. |
| 23 | Publish to PyPI for one-command install (uvx / pipx) | Feature | Yes (no PyPI) | Low | **Partially covered by Phase 3** (`uvx --from git+https://…@vX.Y.Z`). PyPI publishing can be added later if wanted; it needs a PyPI trusted-publisher setup on your account. |

There are no open bug reports. Closed bugs #17, #19, and #21 are fixed on `main`. #19
(multi-key routing) is fixed for per-host tools but **not** for fleet tools (see F1 below).

**Security notes:** no open vulnerability reports. #26 and #29 touch security posture.
My recommendation for both is to keep the current conservative defaults and enforce
policy at the gateway. `.github/SECURITY.md` points reporters to GitHub Private
Vulnerability Reporting, which you need to enable on the fork (section 4).

**Stale doc found during the survey:** CLAUDE.md's "Known gap (strict-xfail)" section
says per-host tools aren't wired to `Registry.resolve_key_for_host`. They are now: every
per-host tool module calls it, and `tests/test_multikey_routing.py` has no `xfail`
left. Low-priority doc fix.

### Open upstream PRs

None. All 11 PRs are closed or merged, so there's nothing to merge.

## 3. Other forks

Upstream has 4 forks: yours (identical to upstream) and the three below. Each was
compared against `swkstudios:main` (`5c08c09`) with `git log` / `git diff` on fetched
refs. No fork code was executed.

| Fork / branch | Commits ahead | What it does | Risk | Proposed action |
|---|---|---|---|---|
| **SvenVanderwegen/mcp-server-unifi** `main` (2026-10-24; branch `claude/project-thread-kdftpa` is the same work minus the last merge) | 9 changes + 9 merge commits, +5110/−73 across 38 files | See F1–F6 below. | — | Port F1, F2, F3. Skip the rest. |
| ↳ **F1** `5974a7b` fix: fleet tools cover every API key | 1 | `list_all_devices`, `list_all_clients`, `get_fleet_summary`, `search_device_fleet`, and `list_devices` (no host) fan out over **all** keys when `key_label` isn't given, instead of only the first key. Records are tagged `_keyLabel` and the summary gets a `byKey` breakdown. Partial-failure semantics match `list_hosts`. **Verified on our `main`:** `tools/aggregation.py:92,121,189,239` use only `_resolve_key(client, None)`, which is the first key. | Low–Med. Changes the output shape (adds `key_labels` / `errors` / `_keyLabel`) only in multi-key setups. Adds fields, never removes them, so it's pass-through-safe. Upstream already tags `_hostName`/`_siteName` the same way. | **Worth porting** (real bug in multi-key deployments). Needs the docs/TOOLS.md and CHANGELOG hunks re-applied without the Entra/per-user doc references. |
| ↳ **F2** `37cf7a1` find consoles by Site Manager name and MAC | 1 | `resolve_host_id` / `resolve_key_for_host` also match `reportedState.name` (the console name shown in Site Manager), case- and whitespace-insensitively, plus MAC addresses in any notation. Unknown non-ID input now gets a clear "Host not found… call list_hosts" error instead of being passed through as a bogus ID. **Verified:** `registry.py:197-201,235-239` on `main` only match `id`, `reportedState.hostname`, and top-level `name`. | Low. Lookup-only, no response changes. The new error for unknown names changes behavior slightly: it used to fail later with a 403. | **Worth porting.** Check the `reportedState.name` field against one live `get_host` before merging. |
| ↳ **F3** `7402733` add read-only `list_traffic_flows`; accept site slug | 1 | New tool: POST search on `/proxy/network/v2/api/site/{site}/traffic-flows` (read-only, returned verbatim). Validates the epoch window, filters, and paging. Site resolution also matches `internalReference` (`default`) after a site is renamed. | Low–Med. The new tool uses a v2 (non-integration) console endpoint, which can drift between firmware versions. It's a POST that reads, so its annotation must be `readOnlyHint=True`. | **Maybe → port.** Useful (flow logs otherwise need the write-gated connector relay). Port the slug-matching part for sure. Port the tool if you want flow logs. |
| ↳ **F4** `4b268af` add `find_hosts` compact index | 1 | New tool returning a hand-picked subset of fields per console. `list_hosts`/`get_host` stay verbatim. | Projection of upstream data in a tool response. | **Skip (pass-through invariant).** A tool that returns a field subset is the kind of response narrowing the invariant forbids. F2 already covers name/MAC lookup. |
| ↳ **F5** `92869e6`, `ecfd56b`, `e595708`, `27de95b` Entra (M365) sign-in, per-user UniFi keys, `/admin` key page | 4 | Adds `entra_oauth.py`, `user_oauth.py`, `oauth_store.py` (**SQLite on a `/data` volume**, Fernet-encrypted keys), `key_admin.py`, and a docker-compose with a persistent volume. | High: auth surface plus persistent credential storage. | **Skip.** Violates the repo's stateless rule (no databases or persistent volumes) and is specific to that org. Your gateway already handles auth. |
| ↳ **F6** `f0e95dc` style web pages with the "VBC Intern" design system | 1 | Org branding, fonts, and logos. | n/a | **Skip.** Specific to that org. |
| **thuer-it/unifi-fabric-mcp-server** `main` (2026-07-12) | 3 (based on v0.3.155, 2 releases behind) | Multi-key MSP fix: pass `key=` through `resolve_host_id` / `resolve_site_slug` across all per-host tools. | n/a | **Skip (superseded).** Upstream v0.6.0 wired `resolve_key_for_host` into every per-host module (`network`, `clients`, `device_mgmt`, `protect`, `firewall_proxy`, `vpn`, `hotspot`, `statistics`, …). Rebasing 1.2k lines onto 0.6.2 would only cause conflicts. |
| **rhkiswani/unifi-fabric-mcp-server** `main` and `safeskill-scan-…` (2026-05-02) | 1–2 (unrelated history, a v0.3.14 snapshot) | Adds a "SafeSkill 50/100" badge to the README (upstream closed this as PR #16). | n/a | **Skip.** Cosmetic third-party badge on stale history. |

**MCP tool annotations:** no one has added them. There are 0 hits for
`readOnlyHint|destructiveHint|ToolAnnotations` on upstream `main` and on every fork
branch, and no upstream issue requests them (#27 is related but doesn't mention them).
Phase 4 is new work.

## 4. Release / deploy fixes needed

| Location | Problem | Fix (Phase 3) |
|---|---|---|
| `.github/workflows/publish.yml:12` | `IMAGE_NAME: swkstudios/unifi-fabric-mcp-server`, so a push from the fork fails with denied, or targets the wrong package. | Derive from `${{ github.repository }}`, lowercased. |
| `.github/workflows/publish.yml` (whole) | Manual dispatch only. Requires the tag to exist already. No version check, no CI gates, no git tag creation, no GitHub Release. `permissions: contents: read`. Its `actions/checkout@de0fac2…` SHA is older than the one in `ci.yml` (`3d3c42e…` v7.0.1) and has no version comments. | Rewrite: `workflow_dispatch(tag)` + `push: tags: v*.*.*`. Then validate → verify `pyproject` version → reuse CI gates (make `ci.yml` callable via `workflow_call`) → create and push the tag if missing (`contents: write`) → multi-arch GHCR build (`vX.Y.Z` + `latest`) → GitHub Release with the `CHANGELOG.md` section as notes. Keep SHA pins. |
| `.github/CODEOWNERS` | `* @swkstudios`, plus a header comment naming upstream | `@elliotmatson` |
| `.github/workflows/lint-public-language.yml` | Every scan step is gated on `github.repository == 'swkstudios/…'`, so it's a silent no-op on the fork. Its blocklist (upstream's internal agent names, `CLAUDE\.md`, private-IP regexes) and its author-email allowlist (`users.noreply.github.com` or `noreply@swkstudios.com`) are upstream policy. | **Your decision is needed.** (a) Retarget to the fork: then commits authored as `noreply@anthropic.com` or your org email **fail** the email check, and any PR body that mentions "CLAUDE.md" fails. I'd have to add your addresses to the allowlist and drop the `CLAUDE\.md` term. (b) Delete the workflow (my recommendation, since it enforces upstream's private-vocabulary hygiene, not yours). (c) Leave it as a no-op. |
| `README.md` (16 refs) | CI badge and clone URL point to upstream. 10× `ghcr.io/swkstudios/...:0.6.1`, an image tag with no matching git tag, and one that doesn't match `pyproject` 0.6.2. Issue links point to upstream. | Point everything at `elliotmatson`. Pin examples to the release being cut (`0.7.0`). Add the uvx git install line. Add a "Fork notice" section. |
| `docs/AUTH-OAUTH.md:79,103,135` | `ghcr.io/swkstudios/...:0.5.0` | Fork image, current version |
| `CONTRIBUTING.md:39,45,175` | Issues and Discussions links point to upstream. Line 75 mentions the internal `dev` branch. | Point to the fork. Enable Discussions or remove that link. |
| `CLAUDE.md:189` | Changelog issue-link format hardcodes `swkstudios/...` | Point to the fork's issues, keeping the instruction that upstream issues may be referenced with an explicit `swkstudios#N` form. |
| `CHANGELOG.md:35,152,413,447` | Links to upstream issues #17 and #19 | **Leave as-is.** They're historical and correctly point to upstream. |
| `.github/ISSUE_TEMPLATE/bug_report.md:30` | Generic `ghcr.io/…` placeholder | Fine as is. |
| `LICENSE` / `NOTICE` | "UniFi Fabric MCP Server contributors" (MIT) and the Ubiquiti trademark notice | **Keep intact.** The fork notice links upstream. |
| Git tags | Upstream has no `v0.6.1` tag (README's pinned version). No PyPI. | The new release flow creates tags. `v0.7.0` will be the fork's first release. |
| uvx git install | `pyproject` uses hatchling with `packages = ["src/unifi_fabric"]` and an entry point `unifi-fabric-mcp`. It should build from a git ref. **Not yet tested.** | Phase 3 step 4: test `uvx --from git+…@<ref> unifi-fabric-mcp` over stdio. |

**GitHub web UI steps for you** (I'll repeat these after Phase 3):
1. Fork → Settings → Actions → General: enable Actions on the fork, and set "Workflow
   permissions" to **Read and write**, or rely on per-job `permissions:` (the new
   workflow declares `contents: write`, `packages: write`).
2. After the first publish: Your profile → Packages → `unifi-fabric-mcp-server` →
   Package settings: set visibility to **Public**, and link the package to the repo.
3. Settings → Code security: enable **Private vulnerability reporting** (SECURITY.md
   relies on it).
4. Optional: create the `skip-changelog` label (the `changelog-check` workflow reads
   it), enable Discussions or drop that link, and add branch protection on `main`
   requiring the CI checks.

## 5. Recommended order of work

1. **`chore/fork-release`** (Phase 3): retarget publish, unified tag/dispatch release
   flow, CODEOWNERS, README/docs/CONTRIBUTING/CLAUDE.md refs, fork notice,
   lint-public-language decision, uvx-from-tag stdio smoke test. Also fix the stale
   CLAUDE.md "Known gap" paragraph.
2. **`feat/tool-annotations`** (Phase 4): `_annotations.py` + explicit `TOOL_CLASS`
   for all 283 tools, `annotations=` on every `@mcp.tool`, `tests/test_annotations.py`,
   TOOLS.md column, CHANGELOG.
3. **`fix/multikey-fleet-tools`**: port F1 (Sven `5974a7b`), adapted, with multi-key
   tests on the shared `multikey_client`/`multikey_registry` fixtures.
4. **`fix/host-name-mac-resolution`**: port F2 (`37cf7a1`) plus the site-slug part of F3.
5. *(optional)* **`feat/list-traffic-flows`**: port the F3 tool, annotated read-only
   (it only becomes "283+1" tools if you want it before the release).
6. *(optional)* **`fix/connector-write-message`**: #29's error message and docs only.
   The default stays off.
7. **Release v0.7.0** after you've merged the PRs you want in it. Items 3–6 can go in
   0.7.0 if they merge first, or ship in 0.7.x.

Skipped: #24, #25, #26 (invariant), #28 (statefulness), Sven F4 (invariant), F5
(stateful auth), F6 (branding), the thuer-it fork (superseded), and the rhkiswani fork
(cosmetic).
