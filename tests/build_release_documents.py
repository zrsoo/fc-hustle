"""Render release tables from independently checked retained observations.

Only writes new 001c-07 documents; never runs recorded native commands.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fc_access import release_audit_v1 as audit


def link(path):
    target = path[len("docs/research/"):] if path.startswith("docs/research/") else "../../" + path
    return f"[{path}]({target})"


def matrix(doc):
    text = """# Objective 001C capability matrix and release decision

**Decision: CONDITIONAL GO for foundation reuse and prerequisite work. Objective 002 actor execution remains gated.**
The five permitted capability classifications describe precisely scoped observations, source contracts or offline checks.
The release decision is separate from capability classification. `live-UNVERIFIED` explicitly marks unwitnessed events.
Current live request evidence below means the latest retained Objective 001C observations, not a fresh account check at audit time.
Objective 001/001B evidence stays historical; no EA command was issued by this audit.

The independent [release record](001c/001c-07/release.json), [validator](../../fc_access/release_audit_v1.py),
[E2E account report](001c-e2e-report.md) and [engineering handoff](001c-architecture-handoff.md) define the release boundary.
All paths are repository-relative evidence correlations. Hashes pin the task-entry bytes, including unrelated work.
Hashes establish local consistency rather than an EA attestation; semantic checks also reconcile wire/entity projections and ledgers.

| Operation | Implementation | Source contract | Current retained live request evidence | Independent result / side-effect proof | Classification and scope | Unresolved dependency |
|---|---|---|---|---|---|---|
"""
    for r in doc["operations"]:
        cells = [r["id"], "; ".join(map(link, r["implementation"])), "; ".join(map(link, r["source_contract"])),
                 "; ".join(map(link, r["evidence"])) or "None witnessed", "; ".join(map(link, r["independent_proof"])) or "None for this live branch",
                 r["classification"] + ("; " + r["live_annotation"] if r["live_annotation"] else "") + ". " + r["scope"], r["dependency"]]
        text += "| " + " | ".join(c.replace("|", " / ") for c in cells) + " |\n"
    text += """
Critical prerequisites are the strict native rules/adapter integration, active outbid/minimum rebid readbacks,
competitive WON ownership and move/list proof, and whole-queue timing/coverage. There is no unconditional GO.
The exact continuation bounds and locked-strategy discrepancies are in the handoff. Passing fixture tests never upgrades these branches.
"""
    return text


def state(t):
    r = t["result"]
    if r.get("credits") is not None:
        return "spendable=" + str(r["credits"])
    rows = r.get("rows") or []
    if t["operation"] == "bid":
        return "requested=" + str(t["params"]["amount"]) + "; ACK only (readbacks required)"
    if len(rows) == 1:
        a = rows[0]
        return "; ".join(f"{k}={a.get(k)}" for k in ("trade_id", "item_id", "definition_id", "current_bid", "bid_state", "trade_state", "expires"))
    return f"rows={len(rows)}; see capture for exact identities/preconditions"


def e2e(doc, timeline, facts, checks):
    text = f"""# Objective 001C independent E2E report

Audit timestamp: **{doc['audited_at']}**. Decision: **CONDITIONAL GO**; actor execution remains gated.
This is a read-only audit of retained 2026-11-13 observations. It makes no claim about the account at audit time.
The [independent validator](../../fc_access/release_audit_v1.py) reads captures and immutable SQLite directly, without importing prior audit or execution code.
The [claims record](001c/001c-07/release.json) and [task-entry preservation map](001c/001c-07/entry.json) are versioned.

Four separately bounded windows contain **44 native requests, 42 reads and two bid PUT attempts**.
Original: 18 commands / one 700 request. Resume 01: four reads / 120 seconds. Resume 02: 18 commands / one 800 request,
900 seconds, 40-read ceiling, two-bid/four-mutation ceilings, gross 2000, individual 1000 and reserve 5000.
Resume 03: four reads / 120 seconds. Every window is closed. No deadline or consumed budget was reset.
These are explicit command counts; unrelated Web App background traffic is outside the instrumentation scope.

The original 700 command (`6371060d0cef5803cffa1797eddc6264`) concerned
`trade:83105610f7508574b2e36139`, `item:178f6a3fd2bc1c19690e3ffe`, version 261855.
Its PUT returned HTTP/native 200 but the request body amount and independent leading readback were not retained.
Historical acceptance remains **UNVERIFIED**; it is not counted as a verified enrolled loss.
Separate exact terminal status later showed closed/non-leading, no acquired item and spendable 16268.
The [original failed checkpoint](001c/001c-06/report.json) remains unchanged.

The successful minimum first participation was on **{facts['identity']['trade_id']}**,
physical **{facts['identity']['item_id']}**, exact PC version **261855**.
Fresh maxBid=1000/minBuy=10500 search, independent wire rows, native caps and >=5 exact-version comparables preceded entry.
12 asks survived nine outlier exclusions: target 2800, projected tax 140, X=500, downward-rounded cap 2100.
The test separately limited bids to 1000. Existing current bid 750 required minimum **800**, not a jump to the cap.
At 2026-11-13T03:28:00.868Z, command `edf54a0285e16ea5ad508fa594721711` sent native `services.Item.bid(item,800)`.
The wire allowlist retained numeric bid=800, HTTP/native 200, native {facts['bid_native_ms']:.3f} ms and host {facts['bid_host_ms']:.3f} ms.
Separate post-ACK GETs proved active/highest at 800 and spendable 15468; the journal then reconciled the command.
Two fresh leading HOLD decisions reserved no further native commands or exposure; exactly one bid write occurred in Resume 02.
The estimator's nested acquisition_price=10500/expected_profit=-7840 is a hypothetical BIN reference, not payment.
Projected profit at 800 was 1860 before a possible sale; no sale was observed.

Account accounting at the last retained independent readbacks:

| Asset / exposure | Before | After verified entry | After separate terminal reconciliation |
|---|---:|---:|---:|
| Spendable coins | 16268 | 15468 | 16268 |
| Held amount inferred from leading/debit | unknown for original attempt | 800 | 0 |
| Actual paid competitive acquisition cost | 0 | unresolved pending outcome | 0 |
| New owned / unsold test cards | 0 | 0 confirmed | 0 |
| Active unresolved bids | original acceptance unknown | one confirmed | 0 |

Gross reservations **1500** are 700+800 across separate windows, not 1500 spent.
The 800 available-coin recovery and exact terminal LOST support returned funds; direct held balance and transient refund time were not exposed.
No WON item, move/list write, completed sale, sale proceeds or realized profit is claimed. One expired outbid Transfer Target remains untouched.
The terminal price **1200** and closed/outbid status agree in independent lite and full watched responses.
Lite definition_id=0 is an omitted version; only the full watched row supplies 261855.
A missing auction never becomes LOST solely by absence.

Native watched durations in Resume 02: {', '.join(f'{x:.3f}' for x in facts['watched_native_ms'])} ms.
Active refresh start intervals: {', '.join(str(x) for x in facts['refresh_intervals_s'])} seconds.
These manual samples do not establish a 25-second cycle. The requested sample was interrupted; no catch-up command was replayed.
Expiry snapshots before/after entry were 1037/1036, then 978/929/888 and terminal -1.
Active outbid/rebid, timer extension, live 25-second whole-queue monitoring, competitive WON transfer/list and sale/profit remain **live-UNVERIFIED**.
The terminal observation occurred after the outage in Resume 03, not inside the expired Resume 02 window.

The complete sanitized commands below are canonical standalone argv recorded by the captures. Some actual invocations were Python stdin
calling capture.main sequentially; these argv are reproductions, not a claim about the literal shell parent process.
They are historical provenance: do not replay mutations or reopen any consumed window. Local decision RPCs are documented below.
Each row includes UTC network start/end, HTTP/native status, host/native duration, ledger state, actual observed result and capture link.
The full [machine timeline](001c/001c-07/commands.json) also retains native request parameters and wire/entity rows.

| Window / stage / command | UTC start -> end | Status / host ms / native ms | Ledger state and actual result | Exact sanitized argv / capture |
|---|---|---|---|---|
"""
    for t in timeline:
        n = t["network"]
        cells = [t["window"] + "/" + t["stage"] + " `" + t["command_id"] + "`", n["started_at"] + " -> " + n["ended_at"],
                 f"200/{n['status']} / {t['host_ms']:.3f} / {n['duration_ms']:.3f}", t["state"] + "; " + state(t),
                 "`" + json.dumps(t["argv"], separators=(",", ":")) + "` " + link(t["capture"])]
        text += "| " + " | ".join(c.replace("|", " / ") for c in cells) + " |\n"
    text += """
Local decisions are not additional EA writes: [reconcile-opening](001c/001c-06-resume-02/reconcile-opening.json),
[hold-opening](001c/001c-06-resume-02/hold-opening.json), and [hold-cycle-2](001c/001c-06-resume-02/hold-cycle-2.json)
retain actual argv, RPC request parameters, counters and results. Durable events tie status/balance read IDs to the bid command.
The [closed window](001c/001c-06-resume-02/closed.json) proves no native request after expiry.

Independent reproduction and actual results follow. These offline commands create only temporary fixture state.
The historical failing gate is retained as a failed result. Full discovery failures are reviewed below, not silently converted to passes.
Complete stdout/stderr, timestamps, exit codes and SHA-256 are in [checks.json](001c/001c-07/checks.json).

| Exact argv | Actual exit | Retained output |
|---|---:|---|
"""
    for c in checks["checks"]:
        text += f"| `{json.dumps(c['command'])}` | {c['exit_code']} | {link(audit.OUT + c['output'])} |\n"
    text += """
Full discovery ran **361 tests**, with two pre-existing failures, both in test_browser_access:
`test_criterion_0_inspection_is_current_and_does_not_assume_cdp` rejects an inspection older than 86400 seconds;
`test_review_matches_executed_bridge_sources_and_retained_metadata` rejects stale live-v2 observations
(`stale_live_evidence`, `no_current_page_observations` and dependent freshness errors).
Rewriting sealed dates to make those historical assertions green would destroy provenance. Their current failure remains explicit.
The original `check_e2e_v1_acceptance.py` exits 1 for missing verified opening/HOLD in its original window;
the independent aggregate completion validator passes using separately retained supplemental evidence.
Legacy rejected-HTTP fixtures use run_offline_suite.py to coalesce headers/body in one send on Windows,
with unchanged assertions/responses and no retries. Earlier plain-client WinError 10053 failures remain in 001c-05 logs.
The complete staged `git diff --cached --check` exits 2 for retained log CRCRLF/trailing blank lines;
the scoped source/tests/release-document whitespace check passes. Exact argv, actual exits and full outputs are in
[git-checks.json](001c/001c-07/git-checks.json). Sealed logs were preserved byte-for-byte instead of normalized.

Release validation additionally runs `python tests/test_release_audit.py` and `python tests/check_release_publication.py`.
The latter verifies actual main ancestry, byte-for-byte committed payload, remote main equality and exclusions.
[Release check output](001c/001c-07/release-checks.json) records the new audit test run; Git publication is checked independently against the remote.
The [payload manifest](001c/001c-07/payload-manifest.json) hashes source, tests, docs and sanitized versioned evidence.
Pre-existing files are checked against all 645 task-entry hashes; unrelated AGENTS.md is preserved and excluded from the commit.
Ignored .orchestrator/private-captures state and working SQLite/WAL/shm files are excluded from publication and untouched.

No extra live experiment was launched for the audit. Remaining live branches require the separately bounded continuation in
the [handoff](001c-architecture-handoff.md), never a replay of the original commands. No autonomous actor loops are included.
"""
    return text


def main():
    result = audit.audit()
    timeline, _ = audit.collect()
    doc = audit.load(audit.OUT + "release.json")
    checks = audit.load(audit.OUT + "checks.json")
    (audit.ROOT / "docs/research/001c-capability-matrix.md").write_text(matrix(doc), encoding="utf-8")
    (audit.ROOT / "docs/research/001c-e2e-report.md").write_text(e2e(doc, timeline, result["facts"], checks), encoding="utf-8")
    (audit.ROOT / audit.OUT / "commands.json").write_text(json.dumps(timeline, indent=2) + "\n")
    (audit.ROOT / audit.OUT / "independent-result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
