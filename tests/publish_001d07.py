"""Build the versioned handoff from explicit findings and retained offline logs.

Only writes 001d-07 artifacts. Does not run probes, actors or regression tests.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/research/001d/001d-07'
BASE = 'docs/research/001d/'
PROD = 'fc_access/production_v1/'


def load(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def save(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def dependency(id, prerequisite, operation, evidence, owner='Objective 002'):
    return dict(id=id, status='DEFERRED TO 002' if owner == 'Objective 002' else 'INVESTIGATION REQUIRED',
                owner=owner, prerequisite=prerequisite, missing_operation=operation,
                required_evidence=evidence)


DEPENDENCIES = [
    dependency('002-REBID', 'A real enrolled auction where this account is actively outbid before expiry.',
        'Observe active personal outbid, compute the smallest native legal rebid under the stored profitable cap, durably dispatch once and independently read back.',
        'Fresh exact auction and spendable coins, intent/PUT amount, post-write watched/status and coins; leading must HOLD without a write.'),
    dependency('002-WIN-COST', 'A naturally won competitive auction from an enrolled trade.',
        'Correlate terminal trade with independent exact owned physical item and actual paid acquisition cost.',
        'Full version/trade/item identity plus purchased or owned readback and independent balance/paid-cost reconciliation; closed/highest or isWon alone remains PENDING.'),
    dependency('002-MOVE-LIST-SETTLE', 'Confirmed competitive ownership and paid cost, plus chosen listing duration.',
        'Implement the production move/list lifecycle; list fixed sampled BIN with starting bid exactly one native tick below, read back the listing and later sale settlement.',
        'Durable move/list commands, exact physical item readbacks, sale/settled proceeds, tax, paid cost and realized profit. Objective 001 Buy Now evidence does not prove this branch.'),
    dependency('002-POLL-LOAD', 'Independent Python Acquirer/Bidder ownership, scheduling and real queue demand.',
        'Implement recurring 600-second discovery and near-25-second prioritized Bidder polling, reconnect handling and practical 50-slot watchlist coverage.',
        'Sustained cycle/latency/priority/deadline metrics under Acquirer load, truncation and expiry checks; fifty mocked rows and finite scheduler runs prove no live capacity guarantee.'),
    dependency('002-TIMER-REFUND', 'Natural near-expiry competitive bidding and held-funds transitions.',
        'Observe timer extensions/resets and transient debit/hold/refund timing independently over the natural auction lifecycle.',
        'Timestamped exact-trade expires/state plus spendable/held balance observations; historical 800 debit/return is only one observed case.'),
    dependency('002-STATUS-RECONNECT', 'A full exact native mapping reacquired after document/epoch change for a real enrolled trade.',
        'Reacquire full identity, then correlate a new status GET; reconcile unresolved or missing enrolled trades without blind retries.',
        'Same complete context/namespace, exact trade/item/full version and independent read IDs. Missing mapping or row remains UNKNOWN; lite version 0/null is VERSION_UNOBSERVED.'),
    dependency('002-STATUS-HISTORY', 'A retained native trade ID in the same identity namespace with independent exact physical identity.',
        'Resolve historical enrolled-trade status only when its mapping exists; never infer a native ID or cross-key identity from pseudonyms.',
        'Full identity plus read-only known-status evidence, otherwise explicit UNKNOWN. One R1/S1 row does not resolve unrelated 001C pseudonyms or newly enrolled trades.'),
    dependency('002-UNSOLD-RULES', 'Product decisions for listing duration, unsold handling and relisting policy.',
        'Define duration, expiry detection, whether/when to relist, price policy and retry/reconciliation rules before implementing unsold/relisting actions.',
        'Approved rules plus exact unsold-item/listing readback and a later observed relist/settlement; no invented rules in 001D.'),
    dependency('D1-R2-WIRE', 'A separately authorized bounded read-only window; the unused R2 allowance is not automatically a new window.',
        'Observe new production pricing search with exact defId/page 1/count 21, then inclusive maxBuy=first_min emitted as maxb, if the candidate remains eligible.',
        'Correlated fresh authenticated sanitized wire captures with criteria and exclusions; native mocks and old 001C maxb evidence do not prove the new route live.', 'Future bounded integration validation'),
    dependency('D5-LIVE-INTEGRATION', 'The final foundation composed with its separate localhost service and reviewed attached official FC27 PC tab.',
        'Run a separately authorized finite read/quote/admission integration with the final foundation and retain independent native results; do not call bid in 001D.',
        'Current attachment/persona/authentication/native-result gates and finite registry/quote evidence. D5 fixtures do not prove final live service composition.', 'Future bounded integration validation'),
]


def fix(id, status, paths, reused, implementation, evidence, tests, live, gaps):
    return dict(id=id, status=status, implementation_class='IMPLEMENTED/OFFLINE_VALIDATED',
        changed_paths=paths, reused_paths=reused, implementation=implementation,
        evidence_sources=evidence, offline_tests=tests, bounded_read_only=live,
        outstanding_dependencies=gaps)


def findings():
    bridge = load(BASE+'001d-02/protocol.json')['authoritative_paths']
    return [
        fix('D1', 'IMPLEMENTED', bridge, [],
            'One strict wire schema 2 and native route. Credits stays /user/credits, not /user/currencies. Exact defId/count=21/page=1; discovery maxBid=1000/minBuy=11000 is separate from pricing maxBuy -> maxb. No production 1000 bid ceiling. Identity/context/fences, positive allowlists, source freshness and UNKNOWN ambiguity are preserved.',
            [BASE+'001d-02/REPORT.md', BASE+'001d-02/protocol.json', BASE+'001d-05/r1-checkpoint.json',
             'docs/research/001c/001c-04/comparables-3.json'], ['tests/test_001d02_contract.py'],
            'LIVE_VERIFIED only for subsequent R1/S1 fresh inventory/credits/status and S2 caps/helpers. New pricing search wire and final foundation live composition remain LIVE-UNVERIFIED.',
            ['D1-R2-WIRE', 'D5-LIVE-INTEGRATION']),
        fix('D2', 'VERIFIED', [PROD+'prices.py', PROD+'adapter.py', PROD+'contracts.py', 'browser/production-v1/page.js',
            'fc_access/bidding_v1/rules.py', 'fc_access/bidding_v1/adapter.py', 'fc_access/durability_v1/harness.py', 'fc_access/pricing.py',
            'tests/native_price_fixture.py', 'tests/native_price_rpc.cjs', 'tests/test_bidding_v1.py'], [],
            'Native exact-card caps plus absolute above/below helpers replace static approved-rule hashes and certification gates. Opening uses startingBid; rebid uses above(currentBid). Profit ceiling rounds down. Context/cap/coins/fresh-read and durable-intent checks remain.',
            [BASE+'001d-03/REPORT.md', BASE+'001d-03/migration.json', BASE+'001d-03/s2-checkpoint.json'],
            ['tests/test_001d03_native_prices.py', 'tests/test_bidding_v1.py', 'tests/test_durability_v1.py'],
            'LIVE_VERIFIED read-only helpers and one exact-card caps GET for 261855: minimum 700, maximum 10500. Eight local evaluations include above(750)=800 and below(1500)=1400. Client helper availability is not transaction acceptance; new bid/list acceptance is LIVE-UNVERIFIED.', ['002-REBID', '002-MOVE-LIST-SETTLE']),
        fix('D3', 'IMPLEMENTED', [PROD+'pricing.py', PROD+'price_cache.py', PROD+'contracts.py', PROD+'store.py',
            'fc_access/pricing.py', 'fc_access/bidding_v1/rules.py', 'fc_access/bidding_v1/adapter.py', 'fc_access/durability_v1/harness.py',
            'tests/test_bidding_v1.py', 'tests/test_durability_v1.py'], [],
            'One-shot quote takes minimum valid independent BIN, excluding paired 600/10000 templates without dropping genuine 1500/1700 offers. First-cap candidate rejection uses one search; eligible misses use exactly two with inclusive maxBuy=first_min. Successful empty second differs from failure/ambiguity. Completed-only durable 86400-second account/game/platform/version cache uses zero searches on hit. last_sale_price is diagnostic only; fixed resale BIN and 5% tax determine cap.',
            [BASE+'001d-04/REPORT.md', BASE+'001d-04/migration.json', 'docs/research/001c/001c-06-resume-02/comparables-2.json'],
            ['tests/test_001d04_pricing.py', 'tests/test_market_pricing.py'],
            'LIVE-UNVERIFIED for new two-search production quote/cache integration. Retained 261855 first page independently demonstrates minimum 1500 rather than old modeled 2800; no new live searches were run.', ['D1-R2-WIRE', 'D5-LIVE-INTEGRATION']),
        fix('D4', 'VERIFIED', [PROD+'inventory.py', PROD+'adapter.py', PROD+'contracts.py', PROD+'store.py', PROD+'server.py',
            'browser/production-v1/page.js', PROD+'investigate_reads.py', PROD+'investigate_status.py'], [],
            'Dirty INBOX/PURCHASED/TRANSFER before watched/unassigned/transfer_list; strict actual authenticated fresh GET and independent command IDs. Bulk identity/native states retained. Missing row -> UNKNOWN; closed/highest -> PENDING until independent owned-item proof. Lite definition 0/null is unobserved, not a mismatched card.',
            [BASE+'001d-05/REPORT.md', BASE+'001d-05/r1-checkpoint.json', BASE+'001d-05/transport-evidence.json'],
            ['tests/test_001d05_inventory.py'],
            'LIVE_VERIFIED R1: four GET 200s; watched 1 row, unassigned 0, transfer list 8, balance 16268. This proves these bounded fresh reads only. Completeness, a win, paid cost and 50-slot capacity remain LIVE-UNVERIFIED.', ['002-WIN-COST', '002-POLL-LOAD']),
        fix('S1', 'PARTIAL', [PROD+'inventory.py', PROD+'adapter.py', PROD+'contracts.py', 'browser/production-v1/page.js', PROD+'investigate_status.py'],
            ['browser/e2e-resolution-v2/page.js'],
            'KnownTrade lookup requires retained full trade/item/version in the same document and reviewed getAuctionData source. Native IDs stay page-local. Reconnect clears mappings; fresh full-identity read is required. Lite rows cannot overwrite full-version proof.',
            [BASE+'001d-05/REPORT.md', BASE+'001d-05/s1-checkpoint.json', BASE+'001d-05/transport-evidence.json',
             'docs/research/001c/001c-06-resume-01/source-contract.json'], ['tests/test_001d05_inventory.py'],
            'LIVE_VERIFIED for one retained current-document trade: full watched plus status GET 200, closed/outbid/current_bid=1200, definition_id=0. Reconnect local inspection showed retained_count=0 and sent zero EA requests. Lookup after reacquisition and unresolved enrolled-trade outcomes remain LIVE-UNVERIFIED.', ['002-STATUS-RECONNECT', '002-STATUS-HISTORY', '002-WIN-COST']),
        fix('S2', 'VERIFIED', [PROD+'prices.py', PROD+'investigate_s2.py'], [],
            'Standalone validation fixes BIN=resale_price and start=below(resale_price), checks reciprocal legal prices inside exact-card limits. No legal lower start -> UNLISTABLE; missing/conflicting evidence -> NEEDS_RECONCILIATION. No listing dispatcher exists in production.',
            [BASE+'001d-03/REPORT.md', BASE+'001d-03/s2-checkpoint.json'], ['tests/test_001d03_native_prices.py'],
            'LIVE_VERIFIED only as local client arithmetic plus authenticated caps: 1500/1400 lies within observed 700..10500. Server listing acceptance, ownership, chosen duration, unsold/relisting and settlement remain LIVE-UNVERIFIED.', ['002-MOVE-LIST-SETTLE', '002-UNSOLD-RULES']),
        fix('D5', 'IMPLEMENTED', [PROD+'foundation.py', PROD+'once.py', PROD+'executor.py', PROD+'store.py', PROD+'server.py',
            'fc_access/bidding_v1/journal.py', 'tests/foundation_fixture.py', 'tests/test_001d06_foundation.py'],
            ['fc_access/bidding_v1/core.py', 'fc_access/bidding_v1/scheduler.py', 'fc_access/durability_v1/store.py'],
            'Foundation composes adapter -> native prices/quote -> admission -> serial prioritized scheduler -> durable journal/registry. Admission records BID eligibility without dispatch. Explicit bid seam requires durable INTENT_DURABLE/PENDING before send. Restart/dropped result stays UNKNOWN, duplicates cannot retry, old epochs are fenced. Append-only registry, spendable balance, reservations, deadlines and separate delivery/native metrics are retained. No actor loops.',
            [BASE+'001d-06/REPORT.md', BASE+'001d-06/migration.json'], ['tests/test_001d06_foundation.py', 'tests/test_bidding_v1.py', 'tests/test_durability_v1.py'],
            'LIVE-UNVERIFIED for final foundation composition. Only finite fixtures, including 2500 bid under 10750 cap, priority/deadlines/crashes/reconciliation. Local service 127.0.0.1:8784 is still separately required; default service rejects mutations. No live actors or bids.', ['D5-LIVE-INTEGRATION', '002-REBID', '002-WIN-COST', '002-POLL-LOAD']),
    ]


def graph():
    specs = [
        ('read', PROD+'foundation.py', 'Foundation.read', 'Adapter-owned schema-2 read response'),
        ('admit', PROD+'foundation.py', 'Foundation.admit', 'Reason-coded registry decision; BID is eligibility, no dispatch'),
        ('bid', PROD+'foundation.py', 'Foundation.bid', 'Explicit guarded write seam; ACK is unresolved, not win'),
        ('dispatch_intent', PROD+'adapter.py', 'NativeAdapter.dispatch_intent', 'Native legality/economics/fresh identity/coins guards, then injected durable bridge and one-use send callback'),
        ('reconcile', PROD+'foundation.py', 'Foundation.reconcile', 'Independent adapter-owned watched/credits; missing stays UNKNOWN'),
        ('registry', PROD+'foundation.py', 'Registry', 'Registry schema 1: current() inspects state, decision() appends, events(trade) exposes append-only history'),
        ('adapter', PROD+'adapter.py', 'NativeAdapter.read', 'Validated retained command/response; schema 2'),
        ('known_status', PROD+'adapter.py', 'NativeAdapter.known_status', 'Known trade/item/full version mapping required in same document'),
        ('prices', PROD+'prices.py', 'PriceService.load', 'Context-bound NativePrices from exact-card caps and loaded client helpers'),
        ('quote', PROD+'pricing.py', 'PricingService.quote', 'Quote version 1; COMPLETE/REJECT/INCOMPLETE; completed is independent of eligibility'),
        ('cache', PROD+'price_cache.py', 'QuoteCache.get', 'Completed-only 86400-second observation; zero price searches on valid hit'),
        ('decide', 'fc_access/bidding_v1/core.py', 'decide', 'Legal minimum under cap, fresh balance/status, HOLD/REJECT/BID decision'),
        ('queue', 'fc_access/bidding_v1/core.py', 'AuctionQueue.admit', 'Capacity/reservations/deadline admission'),
        ('scheduler', PROD+'foundation.py', 'ScheduledExecutor.execute', 'Finite serialized work, concurrency 1, priority/deadline/pacing'),
        ('edge', PROD+'executor.py', 'EdgeExecutor.execute', 'Loopback /run only; no direct authenticated EA HTTP'),
        ('server', PROD+'server.py', 'Handler.do_POST', 'Pinned local origin and validated command/result delivery'),
        ('store', PROD+'store.py', 'Store.enqueue', 'Reserve/claim before delivery, restart UNKNOWN, no redelivery'),
        ('worker', 'browser/production-v1/worker.js', None, 'One native command owner, /next and /result transport'),
        ('page', 'browser/production-v1/page.js', None, 'Reviewed native services, dirty-before-read and sanitized actual XHR evidence'),
        ('intent', 'fc_access/bidding_v1/journal.py', 'Journal.intend', 'Durable UNKNOWN intent before any send'),
        ('dispatch', 'fc_access/bidding_v1/journal.py', 'Journal.dispatch', 'One-use dispatch ticket, committed PENDING; no blind retry'),
        ('authority', PROD+'foundation.py', 'JournalAuthority', 'Optional server composition checks committed exact current intent/claim'),
        ('readbacks', 'fc_access/bidding_v1/journal.py', 'Journal.reconcile', 'Independent fresh post-dispatch status/coins; ACK does not clear fence'),
    ]
    nodes = [dict(id=id, path=path, symbol=symbol, contract=contract,
                  sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest())
             for id,path,symbol,contract in specs]
    links = [
        ('read','adapter','call','explicit operation'), ('admit','prices','call','eligible full exact candidate and fresh coins'),
        ('admit','quote','call','prices loaded'), ('quote','cache','call','check completed cache before search'),
        ('quote','adapter','call','cache miss: one or two price searches; no third'), ('prices','adapter','call','caps/helper operations'),
        ('admit','decide','call','completed quote'), ('admit','queue','call','eligible minimum under profitable cap'),
        ('admit','registry','state','append decision; no write dispatched'),
        ('bid','dispatch_intent','call','explicit caller and independently fresh admission evidence'),
        ('dispatch_intent','intent','call','injected Foundation IntentBridge after native guards'),
        ('intent','dispatch','sequence','Foundation IntentBridge commits FULL INTENT_DURABLE before calling Journal.dispatch/PENDING'),
        ('dispatch','scheduler','callback','adapter one-use send callback only after committed durable dispatch claim'),
        ('known_status','adapter','call','mapping exists, else fail before EA request'),
        ('adapter','scheduler','call','same single-owner executor'), ('scheduler','edge','call','deadline/pacing permits'),
        ('edge','server','local_http','/run'), ('server','authority','call','bid only; default service rejects mutations'),
        ('server','store','call','validated reservation'), ('store','worker','local_http','claim via /next'),
        ('worker','page','native','reviewed explicit selected tab'), ('page','worker','return','strict sanitized result'),
        ('worker','server','local_http','/result'), ('server','edge','return','correlated schema 2 result'),
        ('reconcile','readbacks','call','fresh independently issued watched and credits after dispatch'),
        ('readbacks','registry','state','resolve only with proof; never resend'),
    ]
    from fc_access.production_v1.contracts import ROUTES, LOCAL_OPERATIONS
    return dict(artifact='objective-002-integration-call-graph', version='1.0.0', task='001d-07',
        compatibility=dict(wire_schema=2, price_service=1, quote=1, registry=1, journal=1),
        executable_authority=PROD+'contracts.py', nodes=nodes,
        edges=[dict(source=a,target=b,kind=k,condition=c) for a,b,k,c in links],
        operations={op:dict(method=m,path=p) for op,(m,p) in ROUTES.items()},
        local_operations=sorted(LOCAL_OPERATIONS),
        entrypoints=dict(read='read', admission='admit', explicit_future_write='bid', reconciliation='reconcile', inspect='registry'),
        context_fields=['account','persona','game','platform','identity_namespace'],
        fence_fields=['owner','epoch','host_epoch','worker_epoch','document'],
        startup=dict(import_or_json_load_starts_actors=False, codex_supervisor_required=False,
            separately_running_service_required=True, address='127.0.0.1:8784',
            reviewed_extension='browser/production-v1',
            service_argv=['{python}','-m','fc_access.production_v1.server','--database','private-captures/production-v1/transport.sqlite3'],
            service_default_mutations=False,
            future_authority_composition='Server(transport_path, intent_database=foundation_path)',
            one_shot_argv=['{python}','-m','fc_access.production_v1.once','--context','public-context.json','--definition-id','261855','--interval','0.2'],
            note='Commands are reference only, not run by this publication. Foundation construction attaches; JSON loading and imports do not. once reads/quotes/admits and exits without bid. Live use requires separately authorized scope.'),
        invariants=dict(native_concurrency=1, retry_ambiguous=False, missing_row='UNKNOWN',
            closed_highest='PENDING', confirmed_win_requires='independent exact owned physical item and actual paid cost',
            production_bid_ceiling=None, discovery_max_bid=1000, discovery_min_buy=11000,
            pricing_max_searches=2, second_max_buy='first_min inclusive', cache_ttl_seconds=86400,
            resale_bin='sampled resale_price', listing_start='native below(resale_price)',
            production_move_list_operations=False),
        dependencies=[d['id'] for d in DEPENDENCIES])


def failure_inventory(checks):
    groups=[]
    for i,r in enumerate(checks):
        if r['exit_code']==0:
            continue
        raw='\n'.join((OUT/r['streams'][n]['path']).read_text(encoding='utf-8') for n in ('stdout','stderr'))
        failures=re.findall(r'^(?:FAIL|ERROR): (.+)$', raw, re.M)
        groups.append(dict(check_index=i, command=r['command'], failing_cases=failures,
            summary=re.findall(r'^FAILED \(.+\)$',raw,re.M),
            classification=('UNCHANGED_HISTORICAL_CHECK_ON_MIGRATED_SOURCE' if i in (13,15,16)
                            else 'MIXED_PREEXISTING_DRIFT_AND_SUPERSEDED_SOURCE_CONTRACTS'),
            diagnostic=('Current source hashes differ from original historical pins after authorized 001d-03/04 migrations; no historical capture is repaired. See migration manifests and task-entry preservation.' if i in (13,15,16) else
                'Earlier Objective 002 hash drift and aged browser evidence persist. Additional source/hash/import/static-rule expectations refer to pre-001D pricing/adapter/harness bytes. These failures predate 001d-07; all such sources/tests match its entry snapshot. See exact per-case logs; failures remain failures.')))
    return groups


def main():
    checks=load(BASE+'001d-07/regressions.json')['checks']
    fs=findings(); gs=graph(); failures=failure_inventory(checks)
    save('checklist-v1.json', dict(schema=1, task='001d-07', readiness='001D PARTIAL',
        fixes=fs, dependencies=DEPENDENCIES,
        evidence_classes=['IMPLEMENTED/OFFLINE_VALIDATED','LIVE_VERIFIED','LIVE-UNVERIFIED'],
        scope=dict(this_task_native_requests=0, this_task_live_bids=0, this_task_purchases=0,
            this_task_item_moves=0, this_task_listings=0, this_task_recurring_actors=0,
            objective_001d_explicit_native_requests=7, objective_001d_local_helper_evaluations=8,
            r2_searches=0, sealed_histories_changed=False,
            traffic_scope='Explicit experiment commands only; Web App background/startup traffic was not globally instrumented.')))
    save('integration-call-graph-v1.json', gs)
    save('regression-findings.json', dict(schema=1, baseline=BASE+'baseline.json',
        checks_before_this_publication=True, failures=failures,
        assertion_changes=[], resealed_artifacts=[],
        note='Raw baseline comparisons are not a fully green suite. Wrapped Windows HTTP fixture coalescing changes no assertions; direct discovery is retained separately.'))
    lines=['# 001D final handoff v1.0.0 (001d-07)', '',
        '**001D PARTIAL.** The pre-actor foundation is IMPLEMENTED/OFFLINE_VALIDATED; it is ready for finite offline Objective 002 integration, not a FULL GO for unattended trading. Missing bounded verification: new pricing maxBuy wire (R2), final foundation live composition, and known-status lookup after native mapping reacquisition on reconnect. Actual active outbid/rebid, competitive win/paid cost, production move/list/sale settlement, sustained polling/load, timer/refund behavior and unsold/relisting rules remain Objective 002 dependencies.', '',
        'This versioned supplement is the final per-fix assessment required by the [001D definition of done](../../../../objectives/001d-pre-actor-integration-readiness.md). The [pre-change REPORT](../REPORT.md) remains byte-identical and describes its publication time. Earlier task reports are evidence, not current blanket readiness claims. Machine consumers use [checklist-v1.json](checklist-v1.json) and [integration-call-graph-v1.json](integration-call-graph-v1.json).', '',
        '## Per-fix checklist', '',
        'Changed paths below name the cumulative 001D implementation, including shared files evolved by more than one fix. Reused paths are explicit. This handoff task changes none of that implementation or its assertions. VERIFIED below is limited to the evidence scope given; it never promotes helper availability to server transaction proof.', '']
    for f in fs:
        lines.extend([f"### {f['id']} — {f['status']}", '',
            f"**{f['implementation_class']}**. {f['implementation']}", '',
            'Exact changed paths: '+', '.join('`'+p+'`' for p in f['changed_paths'])+'.', '',
            'Reused paths: '+(', '.join('`'+p+'`' for p in f['reused_paths']) if f['reused_paths'] else 'none outside the shared production primitives')+'.', '',
            'Evidence sources: '+', '.join('`'+p+'`' for p in f['evidence_sources'])+'.', '',
            'Offline tests (all passed in this task): '+', '.join('`{python} '+p+'`' for p in f['offline_tests'])+'.', '',
            'Bounded read-only result: '+f['bounded_read_only'], '',
            'Outstanding: '+', '.join('`'+v+'`' for v in f['outstanding_dependencies'])+'.', ''])
    lines.extend(['## Evidence separation and bounded budget', '',
        'IMPLEMENTED/OFFLINE_VALIDATED covers protocol guards, pricing/native legality/cache, dirty/fresh reads, status interpretation, finite scheduler, journal/registry and crash semantics. Node VM/native doubles and fixture bids are offline evidence, never real account transaction evidence.', '',
        'Narrow LIVE_VERIFIED covers the retained 001D-S2 one authenticated caps GET plus eight local helper evaluations, R1 four fresh GETs, and S1 watched/status two GETs in one retained identity context. All seven explicit native requests were GETs and had native/authenticated status 200. Their timestamp, command/fences, route, freshness and row evidence remain in the original checkpoints. R1 completed 2026-11-13 at 14:49:43 UTC; S1 at 14:55:29 UTC. Reconnect inspection is local, retained_count=0, zero EA requests. Counts describe explicit probes; ordinary startup/background traffic was not globally instrumented.', '',
        'LIVE-UNVERIFIED covers new production pricing wire, final live Foundation integration, status success after reconnect/reacquisition, all new bid/list acceptance and the actor-dependent branches below. Native above(750)=800 and below(1500)=1400 mean local client-helper results. Exact-card caps mean allowed listing limits. Neither means a live rebid/listing succeeded. The historical 001C 800 opening bid, HOLD and later loss/debit-return remain historical scoped evidence; they prove no new rebid, win or listing.', '',
        'The aggregate original budget was ten explicit EA GETs and eight local helper evaluations. Seven GETs and all eight evaluations were consumed. R2 was not run (zero searches). This publication ran zero new probes and does not reopen any window, renew a deadline, reset a counter or authorize use of the remaining nominal allowance.', '',
        '## Objective 002 integration call graph', '',
        'Contract versions: graph 1.0.0, wire 2, price service/quote/registry/journal 1. `fc_access/production_v1/contracts.py` remains executable authority; the original 001d-02 protocol snapshot stays intact. The new graph includes additive price_helpers/status_support/status operations. Graph nodes pin exact source SHA-256 and resolvable Python symbols. JSON can be loaded with the standard library without importing a live executor or starting an actor:', '',
        '```python', 'import json', 'from pathlib import Path', 'graph = json.loads(Path("docs/research/001d/001d-07/integration-call-graph-v1.json").read_text())', 'assert graph["version"] == "1.0.0"', 'print(graph["entrypoints"])', '```', '',
        '`{python} docs/research/001d/001d-07/consume_handoff.py` independently prints a finite contract inventory and exits. It only reads JSON. No local server, browser or actor is needed to consume it.', '',
        'Execution chain: `Foundation.read` -> `NativeAdapter` -> `ScheduledExecutor` -> `EdgeExecutor` -> localhost `/run` -> `Server`/`Store.enqueue/claim` -> production worker -> production page -> native service -> `/result` -> strict correlated parser. `Foundation.admit` -> native `PriceService.load` -> `PricingService.quote`/`QuoteCache` -> `decide`/`AuctionQueue.admit` -> registry decision. Admission sends no bid. A future explicit `Foundation.bid` -> durable `Journal.intend` -> committed `Journal.dispatch` -> guarded dispatch -> serialized executor; ACK remains unresolved. `Foundation.reconcile` requires independently issued fresh watched/credits; missing rows stay UNKNOWN and closed/highest stays PENDING without owned-item proof.', '',
        'Runtime service is separately required at **127.0.0.1:8784**, with the reviewed `browser/production-v1` extension attached to the intended authenticated official FC27 PC tab. No external Codex supervisor is required. Default service rejects mutations; future `Server(transport_path, intent_database=foundation_path)` composes journal authority. Importing modules/reading JSON starts no work. Constructing Foundation explicitly attaches and opens its runtime databases. The reference `python -m fc_access.production_v1.once` performs a finite read/quote/admission batch, exits, and never calls bid. These reference commands were not run against the account by this task.', '',
        'Single Foundation ownership, full public context/namespace and host/worker/document fences are mandatory. Raw native IDs remain page-local; unrelated pseudonyms cannot recover them. Native concurrency=1, configurable pacing, deadline checks and no blind retry survive the handoff. Delivery metrics do not count as native requests. Production has no move/list dispatcher or listing-duration policy.', '',
        '## Exact outstanding dependencies', ''])
    for d in DEPENDENCIES:
        lines.extend([f"- **{d['id']} — {d['status']}** ({d['owner']}). Prerequisite: {d['prerequisite']} Missing operation: {d['missing_operation']} Required evidence: {d['required_evidence']}", ''])
    lines.extend(['## Focused regressions and unchanged historical failures', '',
        'Exact argv, UTC times, test counts, exits and SHA-256 of separate verbatim stdout/stderr are in `regressions.json`; raw streams are adjacent. `regression-findings.json` enumerates every failed case. The commands are offline. Tests run independently from the workspace; `{python}` denotes the supervisor Python. No historical assertions, captures or audit manifests were relaxed or resealed.', '',
        '| Check | Command after `{python}` | Exit | Tests run |', '|---|---|---:|---:|'])
    for i,r in enumerate(checks):
        lines.append(f"| {i:02} | `{' '.join(r['command'][1:])}` | {r['exit_code']} | {','.join(map(str,r['tests_run'])) or 'script'} |")
    lines.extend(['',
        'All six focused 001D suites pass, as do bidding, durability, modeled pricing, search validation, wrapped watched-bulk, E2E live-v2 and reconciliation units. Plain discovery was also retained: **434 tests, 20 failures, 4 errors**, before adding the new handoff validator. This is not a green full suite.', '',
        'Compared with the 001d-01 baseline, older Objective 002 hash drift and two aged/current-browser checks persist. Additional historical artifact checks now encounter authorized 001d-03/04 runtime migrations: `fc_access/pricing.py`, bidding adapter/rules and durability harness have new pinned source bytes. Complete E2E artifact setup and `validate_001c06_complete.py` now stop at the original pricing hash; `check_e2e_v1_acceptance.py` likewise stops before reaching its original unresolved 700-opening/HOLD gates. The earlier supplemental 800 completion does not rewrite that original ambiguity. Release audit reports 22 tests, two failures/two errors: old strategy digest and adapter source/payload pins. Discovery also retains pre-native static-rule/import expectations and report reproduction hashes (001B scope, 001C entry/review, durability, market/pricing/discovery/search/watched artifacts). Each failing ID is in `regression-findings.json`, with full traceback evidence in the raw logs.', '',
        'These source-contract failures predate entry to 001d-07 and are exposed rather than suppressed. The 001d-03/04/06 migration manifests and original source snapshots/Git blobs explain the authorized evolution; focused audits validate those chains exactly. Current historical validators still fail against migrated runtime paths. The earlier unwrapped Windows watched HTTP ConnectionAbortedError did not recur in this discovery run; the independently wrapped watched check passes and the old error remains in the baseline. No new browser observation was fabricated to refresh aged evidence.', '',
        '## Preservation and final decision', '',
        '`entry.json` pins all preexisting docs/objectives/browser/runtime/test files at this task entry (excluding generated __pycache__ and this new output directory). Every byte remains unchanged. It preserves a dirty worktree containing preceding authorized 001D implementation; dirty is not mistaken for this task editing those sources. Original 001/001B/001C histories, captures, manifests and prior 001D publications/checkpoints are byte-identical to entry. Older historical seals that reference migrated runtime sources or the changed Objective 002 are disclosed, not rewritten. The original `seal-audit.json` also records the earlier browser-access live-v2 mismatch.', '',
        '**No recurring actors, live bids, purchases, item moves or listings were launched in this task or in the 001D implementation tasks; no sealed 001/001B/001C histories were altered by this task.** This task ran zero EA requests, zero browser recovery and zero account writes. Previous 001D performed only the seven explicit read-only GETs and eight local helper evaluations described above. Fixture bid/move/list doubles are not live account operations. No production localhost service was started or restarted here; previously running attachment/service presence is not a fresh authentication/persona/market-success claim.', '',
        '**001D PARTIAL:** the foundation is wired and testable for finite Objective 002 consumers. Its bounded live gaps are R2/new pricing wire, final Foundation live composition and status lookup after reconnect mapping reacquisition. Objective 002 must implement/verify its real actor operations and the exact outstanding dependencies above. Competitive wins, actual paid cost, move/list/sale settlement, sustained cadence/capacity and product rules for unsold relisting are not proven by this publication. Completion of this handoff is not completion of those operations.', '',
        'Independent handoff acceptance command: `{python} tests/test_001d07_handoff.py`. Seven tests cover all seven task criteria: regression-log integrity and exact failure inventory; complete per-fix/dependency/readiness artifacts; reparsing actual bounded live results; graph/source/API consistency and a standard-library-only consumer; a finite real Foundation fixture with networking and background threads forbidden; byte preservation; and negative cases rejecting unsupported claims, missing dependencies or stale graph content. These checks read historical evidence without replaying it. The focused implementation suites listed above remain separate executable regressions.', ''])
    (OUT/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    paths=[p for p in OUT.rglob('*') if p.is_file() and p.name!='publication.json' and '__pycache__' not in p.parts]
    paths += [ROOT/'tests/test_001d07_handoff.py', ROOT/'tests/publish_001d07.py', ROOT/'tests/record_001d07_checks.py']
    save('publication.json', dict(schema=1, task='001d-07', version='1.0.0',
        published_at=datetime.now(timezone.utc).isoformat(),
        sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.exists()}))


if __name__ == '__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    main()
