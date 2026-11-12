"""Write a new immutable analysis/report from retained live observations only."""
import argparse
import json
from pathlib import Path

from .analysis import analyze, XS
from .run import save_new
from .validate import validate


def number(value, digits=3):
    return 'unobserved' if value is None else str(round(value,digits))


def render(run, analysis, verification, directory):
    completed = verification['benchmark_completion']=='COMPLETED'
    title = 'Completed finite live experiment' if completed else 'BLOCKED / PARTIAL live experiment'
    interval = run['observation_interval']
    lines = [f'# Objective 001B live benchmark v1 — {title}', '',
        f"Actual interval: **{interval['start_utc']} through {interval['end_utc']}**; "
        f"{interval['monotonic_seconds']:.3f} monotonic seconds.", '',
        f"Completed windows: **{verification['completed_windows']}/9**. Budgeted EA requests: "
        f"**{verification['actual_EA_requests']}/72**, plus the separately recorded authenticated preflight.", '',
        f"Stop reason: `{run['stop_reason']}`. Account mutations: **0**. "
        'Every retained market row in this report comes from the actual live bridge, not a fixture or historical replay.', '',
        f"Frozen protocol SHA-256: `{run['protocol_sha256']}`. No protocol amendment was activated.", '',
        '## Integration and actual windows', '',
        'The runner reuses the verified port-8771 follow-up bridge, including the live-observed uppercase '
        '`GamePlatform.PC` representation. Original strategy plans, block rankings, budget accounting, '
        'pacing and stop behavior are inherited. The additive wrapper checkpoints each response and '
        'waits through the full final 300-second window on a normal completion. No authentication handling '
        'or browser implementation was replaced.', '',
        '| Window | Strategy | Seconds observed | Completed | Commands | EA requests |',
        '| --- | --- | ---: | --- | ---: | ---: |']
    for window in run['window_intervals']:
        lines.append(f"| {window['window']+1} | {window['strategy']} | {window['observed_seconds']:.3f} | "
                     f"{window['completed']} | {window['commands']} | {window['EA_requests']} |")
    lines += ['', 'The complete planned order remains **A/B/C/B/C/A/C/A/B**. A local failure with an empty '
        '`network` list is charged as a command but is not invented as an EA request. No catch-up requests '
        'or automatic retries were issued.', '',
        '## Discovery and request efficiency', '',
        '| Strategy | EA requests | Unique auctions | Exact versions | Auctions/request | Versions/request | Auctions/observed minute | Duplicate fraction |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name, arm in analysis['arms'].items():
        lines.append(f"| {name} | {arm['EA_requests']} | {arm['unique_auctions']} | {arm['unique_exact_versions']} | "
            f"{number(arm['auctions_per_EA_request'])} | {number(arm['versions_per_EA_request'])} | "
            f"{number(arm['auctions_per_observation_minute'])} | {number(arm['duplicate_fraction'])} |")
    lines += ['', 'Numerators include all returned auctions from the allocated discovery and revalidation '
        'budget; discovery-only counts are also retained in `analysis.json`. Minute denominators use '
        'each arm’s actually allocated window exposure, not wall time spent observing other arms. '
        'Zero returned rows in an authenticated response are genuine empty-query results; an arm '
        'with no observations has **unknown yield**, not zero opportunities.', '',
        'BIN distributions, exact filter/page combinations, overlaps, expiry ordering, empty/cache-only '
        'responses, HTTP errors and all latency samples are retained in [analysis.json](analysis.json) '
        'and [observations.json](observations.json). Bounded expiry-ordered pages are not an exhaustive '
        'market sample; offsets can drift and a lookahead auction may repeat on page two.', '',
        '## Profitability scenarios and revalidation', '',
        '`expected_profit = target_sale_price - target_sale_price // 20 - acquisition_price`.', '',
        'The existing conservative calculator is reused: exact FC27 PC versions, candidate trade/item '
        'excluded from its own comparables, at least five independent comparables, age <=120 seconds, '
        'remaining lifetime >60 seconds, robust MAD filtering and a lower-quartile undercut. Cohorts '
        'contain only already observed data from the same strategy window. No future rows or other '
        'arms’ requests subsidize the comparison.', '',
        '**Native price caps and legal increments remain unverified.** The sensitivity calculation uses '
        'explicitly hypothetical caps/increments, following the earlier research method. Its timestamps '
        'are model evaluation times, not fabricated native-rule observations. Model matches are '
        '**indicative only** and cannot become executable opportunities or realized profit.', '',
        '| Strategy | X=100 | X=250 | X=500 | X=1000 | Verified executable yield |',
        '| --- | ---: | ---: | ---: | ---: | --- |']
    for name, arm in analysis['arms'].items():
        values=arm['indicative_modeled_candidates_by_X']
        lines.append(f"| {name} | "+' | '.join(number(values[str(x)],0) for x in XS)+' | unknown: caps/ticks unavailable |')
    lines += ['', 'Each number counts distinct auctions with at least one qualifying model observation; '
        'repeated observations do not inflate it. Prices are asks, not completed sales. No hourly yield '
        'is extrapolated.', '', '| Strategy | Diagnostic candidates | Fresh identity/BIN/lifetime matches | Match fraction |',
        '| --- | ---: | ---: | ---: |']
    for name, arm in analysis['arms'].items():
        lines.append(f"| {name} | {arm['diagnostic_revalidation_attempts']} | {arm['diagnostic_revalidation_matches']} | "
                     f"{number(arm['diagnostic_revalidation_match_fraction'])} |")
    lines += ['', 'With verified rules unavailable, the frozen fallback selects the lowest positive BIN '
        'for **diagnostic-only** two-page revalidation. A fresh identity/BIN match is not a profitable '
        'executable opportunity. Absence from two bounded pages is not proof of a sale. '
        'Profitable executable revalidation rates and realized profits remain unknown.', '',
        '## Latency', '',
        '| Strategy | Samples | Queue median ms | Native median ms | Python client median ms | Python client p95 ms |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name, arm in analysis['arms'].items():
        t=arm['latency']
        lines.append(f"| {name} | {t['run_request_end_to_end_ms']['n']} | {number(t['queue_delivery_ms']['median_ms'])} | "
                     f"{number(t['native_service_ms']['median_ms'])} | {number(t['run_request_end_to_end_ms']['median_ms'])} | "
                     f"{number(t['run_request_end_to_end_ms']['p95_ms'])} |")
    lines += ['', 'All components retain n/median and nearest-rank p95 only when n>=20. Native service '
        'duration is Web App/observable work, not pure EA server latency. The measured local queue, '
        'worker-to-native dispatch/pacing wait, page projection, result-return residual, independent '
        'result-POST round trip and Python client duration remain separate. An assumed alarm delay '
        'was never subtracted. Page/background timer throttling and the 30-second native guard can '
        'increase dispatch delay even when local queue delivery is fast.', '',
        '## Coverage, third-party prices and recommendation', '',
        f"Passive observation status: **{analysis['background']['status']}**. Missing passive traffic is "
        'unknown, never zero. All allowlisted traffic captured during a native command consumes '
        'foreground budget; traffic outside those intervals remains unmeasured unless the passive '
        'observer actually connects. This limits causal comparisons.', '']
    if not completed:
        lines += ['**NO comparative winner can be selected.** Only a partial prefix of the alternating '
            'experiment exists. It cannot establish whether B improves coverage, whether C improves '
            'candidate yield, or whether A’s two-version watchlist is an adequate market universe. '
            'The narrow next step is to resolve the local extension/idle-period failure and complete '
            'the remaining frozen windows within the remaining request budgets, with any necessary '
            'pause/recovery amendment frozen before further observations.', '']
    lines += ['For Objective 002, retain EA native exact-version PC asks as authoritative. Targeted '
        'search remains a verified integration primitive, not a demonstrated strategy winner. Bounded '
        'hybrid exploration should replace scheduled scans rather than add EA requests, rank only '
        'the preceding completed block and be promoted only after useful candidate-yield evidence. '
        'A two-player watchlist cannot support whole-market conclusions.', '',
        'DataFluxor remains an **unverified optional reference-price candidate** from the prior provider '
        'research. No production data, entitlement or current access was established here and no money '
        'was spent. Exact-PC external references could broaden ranking and watchlist coverage, but '
        'their incremental benefit is unmeasured; they would not resolve missing native caps/ticks '
        'or turn sample asks into verified completed-sale evidence.', '',
        'Specific Objective 002 handoff deltas remain design requirements only: preserve the corrected '
        'persona validation; harden bridge idle/reconnection and command ownership before unattended '
        'use; retain >=30-second EA submission pacing; add fresh native rule provenance; keep discovery, '
        'indicative pricing, fresh revalidation and execution eligibility as distinct states; preserve '
        'the existing durable identity/reconciliation release gates. No production modules were implemented.', '',
        '## Reproduction and recovery', '',
        'The actual capture command was:', '', '```powershell',
        f'python -m experiments.market_discovery_live_v1 --output-dir {directory.as_posix()}', '```', '',
        '**Do not blindly rerun nine windows:** completed windows and consumed EA requests must not be '
        'discarded or replayed outside the budget. This run’s remaining benchmark budgets are '+
        ', '.join(f"{s}={24-analysis['arms'][s]['EA_requests']}" for s in 'ABC')+' requests.', '',
        'Read-only reproduction of retained evidence:', '', '```powershell',
        f'python -m experiments.market_discovery_live_v1.validate --run-dir {directory.as_posix()}',
        'python tests/test_market_discovery_live_v1.py',
        'python tests/test_market_discovery_live_analysis_v1.py',
        'python -m unittest discover -s tests -p "test_*.py"', '```', '',
        'The evidence validator distinguishes integrity PASS from benchmark completion BLOCKED; it '
        'returns nonzero for an incomplete experiment. All historical Objective 001/001B files, '
        'transactions and seals are unchanged. Legacy exact-commit validators are not rewritten '
        'to accept new research files.', '',
        'Minimal current operator action: keep the existing official EA Web App tab open and visible; '
        'inspect the follow-up extension’s full WAIT hover message, then reattach it when the local '
        'server is healthy. No login is requested unless EA actually requires it. No credentials '
        'should be copied. Further market requests remain stopped pending safe recovery.', '']
    return '\n'.join(lines)


def write(directory):
    directory=Path(directory)
    targets=[directory/name for name in ('analysis.json','validation.json','REPORT.md')]
    if any(p.exists() for p in targets):
        raise ValueError('new_report_paths_required')
    run=json.loads((directory/'observations.json').read_text())
    if run.get('mode')!='LIVE_READ_ONLY':
        raise ValueError('live_report_requires_live_lineage')
    analysis=analyze(run,directory)
    verification=validate(directory)
    if verification['integrity_status']!='PASS':
        raise ValueError('live_report_requires_valid_evidence')
    save_new(targets[0],analysis)
    save_new(targets[1],verification)
    with targets[2].open('x',encoding='utf-8') as stream:
        stream.write(render(run,analysis,verification,directory))
    return verification


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(write(args.run_dir)))


if __name__=='__main__':main()
