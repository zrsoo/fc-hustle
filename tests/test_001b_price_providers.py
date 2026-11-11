"""Offline T2 acceptance checks. No live provider/EA calls or credentials needed.

These check retained observations, contracts, citations and claim boundaries.
They establish artifact consistency, not provider authenticity or live uptime.
"""
import copy
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.price_provider_research.collect_http import capture

RUN = Path('experiments/market_discovery/runs/t2-providers-20261111T212333Z')
REPORT = Path('docs/research/001b-price-providers.md')
PINS = {
    'puredan824-hub/fc27-sniffer': 'e1488d6e51bdcafec6eaf61cdb06461358b7844d',
    'liusihang/fc27-copilot': 'fa0fdde132715b2c09a4cff1e51736a1794d635e',
    'jgor80/11-lab': 'fc5e4b04d4effbed3ea8d098db6f38d0a5665224',
}
PROVIDERS = {'futgg', 'datafluxor', 'futdb', 'futbin', 'futwiz', 'ea-community', 'dsfut', 'parse'}


def read(path):
    return json.loads((ROOT / path).read_bytes())


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('UTC timestamp required')
    return result


def load_bundle():
    return {
        'findings': read(RUN / 'providers.json'),
        'sources': read(RUN / 'source-review.json'),
        'documents': read(RUN / 'public-documents.json'),
        'reader': read(RUN / 'reader-review.json'),
        'df_spec': read(RUN / 'datafluxor-openapi-projection.json'),
        'db_spec': read(RUN / 'futdb-openapi-projection.json'),
        'sandbox': read(RUN / 'sandbox-prices.json'),
        'history': read(RUN / 'sandbox-history.json'),
        'denial': read(RUN / 'datafluxor-denial.json'),
        'http': {str(p).replace('\\', '/'): read(RUN / p)['attempts']
                 for p in [Path('http.json'), Path('contracts/http.json'), Path('terms/http.json')]},
        'protocol': read('docs/research/001b/protocol.json'),
        'native': read('docs/research/market/availability.json'),
        'report': (ROOT / REPORT).read_text(encoding='utf-8'),
    }


def semantic_defects(bundle):
    """Cross-check independent evidence; errors are grouped by T2 criterion.

    Does not consult artifact hashes, so negative fixtures exercise the actual
    findings checks independently from the integrity check.
    """
    errors = {i: [] for i in range(6)}

    def need(ok, message, criterion):
        if not ok:
            errors[criterion].append(message)

    try:
        f = bundle['findings']
        m = f['measured']
        providers = {p['id']: p for p in f['providers']}
        sources = {r['repository']: r for r in bundle['sources']['repositories']}
        rows = [row for group in bundle['http'].values() for row in group]
        manifest = [r for r in rows if r['url'] == 'https://r2.fut.gg/27/manifest.json']
        need(len(manifest) == 1 and manifest[0]['status'] == 403 and m['manifest_retests'] == 1,
             'exactly one ordinary manifest retest with observed 403', 0)
        need(all(r['retry_count'] == 0 and r['method'] == 'GET' and not r['authentication_sent']
                 and r['access'] == 'anonymous_public_get' for r in rows), 'ordinary read-only access', 0)
        need(not [r for r in rows if 'r2.fut.gg' in r['url'] and 'manifest.json' not in r['url']],
             'no derived blobs after refusal', 0)
        need(m['direct_public_gets'] == len(rows) == 21, 'request count derived from ledgers', 4)
        by_url = {r['url']: r for r in rows}
        for row in rows:
            start, end = timestamp(row['started_at_utc']), timestamp(row['ended_at_utc'])
            need(start <= end <= datetime.now(timezone.utc), 'actual UTC request interval', 4)
            need(row['elapsed_ms'] >= 0 and abs((end-start).total_seconds()*1000-row['elapsed_ms']) < 100,
                 'elapsed time agrees with wall interval', 4)
            need(type(row['status']) is int and 100 <= row['status'] <= 599
                 and row['bytes_read'] >= 0 and not row['truncated']
                 and re.fullmatch('[a-f0-9]{64}', row['response_sha256']), 'complete HTTP metadata', 4)
            need(set(row['headers']) <= {'content-type', 'date', 'etag', 'last-modified',
                                        'retry-after', 'cache-control'}, 'header privacy allowlist', 4)

        need(set(sources) == set(PINS), 'only three requested repositories reviewed', 1)
        for repo, pin in PINS.items():
            row = sources[repo]
            need(row['revision'] == pin and row['tree_truncated'] is False
                 and re.fullmatch('[a-f0-9]{40}', row['tree_sha']), 'pinned complete source inventory '+repo, 1)
            timestamp(row['review_completed_at_utc'])
            need(row['reuse'] == 'reference_only_no_upstream_execution_or_copying_into_runtime',
                 'bounded review and reuse '+repo, 1)
            need(row['license'] == ('MIT' if repo != 'jgor80/11-lab' else None), 'license status '+repo, 1)
            need(bool(row['license_paths']) == (repo != 'jgor80/11-lab'), 'license tree cross-check '+repo, 1)
            for file in row['files']:
                need(file['url'] == f'https://github.com/{repo}/blob/{pin}/{file["path"]}',
                     'revision-pinned file citation', 1)
                need(re.fullmatch('[a-f0-9]{40}', file['git_blob_sha1']) is not None
                     and re.fullmatch('[a-f0-9]{64}', file['content_sha256']) is not None,
                     'source content identities', 1)
                for anchor in file['anchors']:
                    need(1 <= anchor['start'] <= anchor['end'] <= file['line_count']
                         and len(anchor['text'].splitlines()) == anchor['end']-anchor['start']+1,
                         'nonempty line-addressable excerpt', 1)
        need(sources['jgor80/11-lab']['package_license_field'] is None, 'no invented XI Lab grant', 1)
        source_text = {repo: '\n'.join(a['text'] for file in r['files'] for a in file['anchors'])
                       for repo,r in sources.items()}
        need(all(term in source_text['puredan824-hub/fc27-sniffer'] for term in
                 ['player-prices-index','player-prices-ps5-dyn','streamlined-pool','id0','_published_at']),
             'console index/pool source contract reviewed', 0)
        need(all(term in source_text['jgor80/11-lab'] for term in
                 ['player-prices-pc-dyn','len(statuses) != len(prices)','status == 0','ea_item_id',
                  'manifest["_published_at"]','definitionId','maskedDefId']), 'PC contract and exact identity reviewed', 0)
        need(all(term in source_text['liusihang/fc27-copilot'] for term in
                 ['players/v2/27/', 'card_ea_id','base_player_ea_id','Market prices intentionally excluded',
                  '19676', '2026-09-18']), 'catalog mapping is not price coverage', 1)

        need(set(providers) == PROVIDERS, 'named providers and documented alternatives', 2)
        for p in providers.values():
            need(p['source_refs'] and p['status'] and p['unknowns'], 'evidence-backed candidate outcome', 2)
            description = p['provider_description']
            need(set(description) >= {'contract','batching','platforms','price_meaning','history','cost',
                                     'request_limits','access','terms'}, 'complete contract/access/terms dimensions '+p['id'], 2)
            for ref in p['http_refs']:
                ledger, ident = ref.split('#')
                need(any(r['id'] == ident for r in bundle['http'][ledger]), 'resolvable HTTP evidence reference', 2)
            for ref in p['source_refs']:
                need((ROOT / RUN / ref).is_file(), 'resolvable source reference', 2)
            pm = p['measured']
            need(pm['priced_card_count'] is None and pm['publication_utc'] is None
                 and pm['refresh_seconds'] is None and pm['exact_mapping_verified'] is False
                 and pm['production_quote_rows'] == 0, 'production unknowns must not become measurements '+p['id'], 3)

        df = bundle['df_spec']
        prices = df['paths']['/api/v1/fut/prices']['get']
        params = {p['name']: p for p in prices['parameters']}
        need(params['platform']['schema']['enum'] == ['ps','xbox','pc']
             and '500' in params['ea_ids']['description'] and params['ea_ids']['required'],
             'DataFluxor exact PC/batch contract', 2)
        need(df['components']['securitySchemes']['DataFluxorAPIKey']['name'] == 'X-API-Key'
             and prices['security'] and set(prices['responses']) >= {'401','402','403','429','503'},
             'DataFluxor auth and refusal contract', 2)
        need('200 evenly spaced points' in df['paths']['/api/v1/fut/cards/{futbin_id}/history']['get']['description'],
             'history resolution limit', 3)
        db = bundle['db_spec']
        need(db['info']['version'] == '27'
             and db['components']['securitySchemes']['ApiKey']['name'] == 'X-AUTH-TOKEN'
             and set(db['components']['schemas']['PricesResponse']['properties']) == {'pc','playstation'},
             'FUT-DB game/platform/key contract', 2)
        batch = db['paths']['/api/players/prices']['get']
        need(batch['requestBody']['content']['application/json']['schema']['type'] == 'array'
             and 'one request per player' in batch['summary'], 'batch billing and unusual GET body retained', 2)
        need('FAQ says no multiple prices' in providers['futdb']['provider_description']['batching']
             and 'no way to get multiple' in ' '.join(b['text'] for d in bundle['documents']['documents']
                 if d['url'] == 'https://fut-db.com/' for b in d['excerpts']), 'batch documentation conflict retained', 2)
        expected_status = {
            'https://datafluxor.com/api/v1/fut/prices?ea_ids=233731&platform=pc': 401,
            'https://api.fut-db.com/api/players/1/price': 401,
            'https://www.futbin.com/': 403, 'https://www.futwiz.com/': 200,
            'https://www.fut.gg/': 403, 'https://stormstrike.gg/terms': 200}
        for url,status in expected_status.items():
            need(by_url[url]['status'] == status, 'observed candidate access outcome '+url, 2)
        need(bundle['denial']['success'] is False and bundle['denial']['code'] == 'UNAUTHORIZED',
             'production denial is not successful quote retrieval', 4)
        described = providers['datafluxor']['provider_description']
        need(described['batching']['max_price_ids'] == 500 and described['cost']['monthly'] == 29
             and described['cost']['currency'] == 'USD' and described['cost']['requests_per_month'] == 100000
             and described['request_limits']['per_minute'] == 120
             and described['request_limits']['in_flight_per_key'] == 3
             and described['request_limits']['in_flight_per_organization'] == 6, 'current described DataFluxor costs/limits', 2)
        need(described['pc_priced_versions'] is None and described['catalog_versions_approx'] == 22000
             and described['console_priced_versions_approx'] == 20500
             and described['catalog_measurement_date_by_provider'] == '2026-11-10'
             and described['refresh'] == {'top_5700_list_minutes':8, 'other_list_minutes':25,
                 'top_500_exact_minutes':20, 'quote_stale_minutes':15, 'summary_stale_hours':24,
                 'on_demand_refresh':False}, 'current descriptions distinguished from indexed older text', 3)
        db_desc = providers['futdb']['provider_description']
        need(db_desc['cost']['monthly'] == 79 and db_desc['cost']['currency'] == 'EUR'
             and db_desc['request_limits']['premium_per_day'] == 20000
             and db_desc['catalog_count_is_priced_count'] is False, 'FUT-DB costs and non-price catalog count', 2)
        need('USD per 100,000 coins' in providers['dsfut']['provider_description']['price_meaning']
             and 'NOT_PUBLIC_PRICE_FEED' in providers['ea-community']['status']
             and providers['parse']['status'] == 'INDEXED_DESCRIPTION_ONLY_READER_404',
             'alternatives checked for correct units and entitlement', 2)

        sandbox, history = bundle['sandbox'], bundle['history']
        items = sandbox['data']['items']
        platforms = sorted({i['platform'] for i in items})
        need(sandbox['success'] is True and sandbox['sandbox'] is True and sandbox['credit_cost'] == 0
             and 'Fixed illustrative data' in sandbox['warning']
             and history['sandbox'] is True and 'not live market prices' in history['warning'],
             'explicitly authorized illustrative sandbox classification', 4)
        need(m['sandbox_price_rows'] == len(items) == 2
             and m['sandbox_returned_platforms'] == platforms == ['ps']
             and m['sandbox_requested_platform'] == 'pc'
             and m['sandbox_pc_history_points'] == len(history['data']['points']) == 3,
             'measured fixture counts and platform mismatch', 3)
        need([i['ea_id'] for i in items] == [67340611,231747]
             and [i['futbin_id'] for i in items] == [22950,8]
             and all(timestamp(i['observed_at']) < timestamp('2026-11-11T00:00:00Z') for i in items),
             'sample mappings and times never treated as current observations', 3)
        need(m['successful_production_price_retrievals'] == 0
             and m['successful_sandbox_retrievals'] == 2
             and m['production_priced_card_count'] is None
             and m['usable_broad_fc27_pc_feed_retrieved'] is False
             and f['status'] == 'RESEARCH_COMPLETE_NO_USABLE_BROAD_FEED', 'honest retrieval conclusion', 4)
        need(set(f['evidence_classes']) == {'MEASURED_HTTP','PROVIDER_DESCRIPTION','REPOSITORY_CLAIM','PROPOSED_FALLBACK'},
             'explicit claim taxonomy', 3)

        fb, p = f['fallback'], bundle['protocol']
        need(fb['classification'] == 'PROPOSED_FALLBACK' and fb['status'] == 'DESIGNED_NOT_RUN_IN_T2'
             and fb['game'] == 'fc27' and fb['platform'] == 'pc'
             and fb['identity'] == ['game','platform','definition_id']
             and fb['allowed_operations'] == ['search'] and len(fb['preconditions']) == 3,
             'bounded exact-version native fallback and preflight', 5)
        cov = fb['coverage']
        need(cov['watchlist'] == p['market']['watchlist']
             and cov['unverified_filters'] == p['market']['unsupported_filters']
             and cov['validated_filters'] == ['club','league']
             and cov['pages'] == p['search_pair']['pages']
             and cov['count_including_lookahead'] == 21
             and cov['minimum_gap_seconds'] == p['timing']['minimum_submission_gap_seconds']
             and cov['max_in_flight'] == p['timing']['max_in_flight']
             and cov['max_network_reads_per_window'] == p['budget']['per_window']
             and cov['windows'] == len(p['timing']['order'])
             and cov['max_total_network_reads'] == p['budget']['total_maximum'], 'fallback matches frozen T1 coverage/budget', 5)
        native_rows = [r for a in bundle['native']['attempts'] for r in a['result']['auctions']]
        native = fb['historical_measurement']
        need(native['reads'] == len(bundle['native']['attempts']) == 3
             and native['raw_auction_rows'] == len(native_rows) == 52
             and native['unique_auctions'] == len({r['trade_id'] for r in native_rows}) == 51
             and native['unique_versions'] == len({r['item']['definition_id'] for r in native_rows}) == 2
             and native['benchmark_live_yield'] is None, 'historical coverage recomputed, not live yield', 5)
        need(all(m[k] == 0 for k in ['new_EA_reads','new_account_mutations','subscriptions_purchased','accounts_registered'])
             and m['current_EA_attachment'] == 'NOT_CHECKED', 'no unsupported current access/mutation claims', 5)
        for key,terms in {
            'price_meaning':['excluding candidate', 'Not completed-sale', 'PC'],
            'missing_prices':['UNKNOWN','no borrowing','insufficient'],
            'missing_rules':['Diagnostic-only', 'no executable yield'],
            'freshness':['UTC','cache-only','expires'],
            'history':['Only retained local samples'],
        }.items():
            need(all(term in fb[key] for term in terms), 'fallback pricing/coverage boundary '+key, 5)
        need(len(fb['limits']) >= 5 and len(fb['stops']) >= 3, 'fallback coverage/stop limits explicit', 5)

        report = bundle['report']
        for criterion, phrases in {
            0:['Exactly one retest','No manifest-derived catalog/index/PC URL','placeholder'],
            1:list(PINS)+['MIT','No LICENSE/COPYING/NOTICE','market prices'],
            2:['US$29/month','€79/month','one request per','USD per 100,000 coins','written scraping permission'],
            3:['MEASURED_HTTP','PROVIDER_DESCRIPTION','REPOSITORY_CLAIM','PC priced count is not stated',
               '2026-09-27T21:59:36Z','25 minutes','priceUpdate'],
            4:['No usable broad FC27 PC production feed was retrieved','fixed','401','403','sandbox'],
            5:['EA-native fallback','NOT_CHECKED in T2','52 raw rows','51 unique auctions','UNKNOWN',
               'not an exhaustive market','No buy, bid, move, list or relist'],
        }.items():
            normalized = ' '.join(report.split())
            for phrase in phrases:
                need(phrase in normalized, 'report documents '+phrase, criterion)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        for criterion in errors:
            errors[criterion].append('malformed/incomplete evidence: '+repr(error))
    return {criterion: reasons for criterion,reasons in errors.items() if reasons}


class PriceProviderAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle()

    def test_all_six_criteria_crosscheck_observations_specs_sources_and_report(self):
        self.assertFalse(semantic_defects(self.bundle), semantic_defects(self.bundle))

    def test_criterion_4_manifest_pins_all_retained_artifacts_and_new_implementation(self):
        manifest = read(RUN / 'artifacts.json')
        expected = {str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT / RUN).rglob('*')
                    if p.is_file() and p.name != 'artifacts.json'}
        expected |= {str(REPORT).replace('\\','/'), 'experiments/price_provider_research/collect_http.py',
                     'tests/test_001b_price_providers.py'}
        self.assertEqual(set(manifest['sha256']), expected)
        timestamp(manifest['sealed_at_utc'])
        for path,digest in manifest['sha256'].items():
            target = (ROOT / path).resolve()
            self.assertTrue(target.is_relative_to(ROOT))
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest, path)
        self.assertEqual(hashlib.sha256((ROOT / 'docs/research/001b/protocol.json').read_bytes()).hexdigest(),
                         manifest['t1_protocol_sha256'])
        for name,index in [('sandbox-prices.json',2),('sandbox-history.json',3),('datafluxor-denial.json',1)]:
            row = self.bundle['http']['contracts/http.json'][index]
            self.assertEqual(hashlib.sha256((ROOT / RUN / name).read_bytes()).hexdigest(),row['response_sha256'])

    def test_criteria_2_3_public_excerpts_have_provenance_and_specs_have_no_dangling_refs(self):
        for doc in self.bundle['documents']['documents']:
            ledger,ident=doc['http_ref'].split('#')
            row=next(r for r in self.bundle['http'][ledger] if r['id']==ident)
            self.assertEqual((doc['url'],doc['original_body_sha256'],doc['received_at_utc']),
                             (row['url'],row['response_sha256'],row['ended_at_utc']))
            self.assertTrue(doc['excerpts'])
            self.assertTrue(all(b['text'] and type(b['block']) is int for b in doc['excerpts']))
        text=' '.join(b['text'] for d in self.bundle['documents']['documents'] for b in d['excerpts'])
        for evidence in ['22,000','20,500','2026-11-10','$29','120','79.00','20.000','22,143',
                         '30 minutes and 24 hours','No recurring payments','except where expressly permitted']:
            self.assertIn(evidence,text)
        for key in ['df_spec','db_spec']:
            spec=self.bundle[key]
            def inspect(value):
                if isinstance(value,dict):
                    for k,v in value.items():
                        if k=='$ref':
                            current=spec
                            for component in v.split('/')[1:]: current=current[component]
                        else: inspect(v)
                elif isinstance(value,list):
                    for v in value: inspect(v)
            inspect(spec)

    def test_criterion_4_report_links_resolve_and_retention_has_no_secrets(self):
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)',self.bundle['report']):
            if link.startswith('https://'): continue
            path=((ROOT / REPORT).parent / link).resolve()
            self.assertTrue(path.is_relative_to(ROOT), link)
            self.assertTrue(path.is_file(),link)
        for file in (ROOT / RUN).rglob('*'):
            if not file.is_file(): continue
            raw=file.read_text(encoding='utf-8')
            self.assertNotRegex(raw,r'(?i)(?:set-cookie|x-ut-sid|x-ut-phishing-token|access_token|refresh_token)["\s]*:')
            self.assertNotRegex(raw,r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----')
            self.assertNotRegex(raw,r'(?i)\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}')
            self.assertNotRegex(raw,r'(?i)"(?:account_id|persona_id|session_id|cookie|password)"\s*:')

    def test_each_criterion_rejects_material_false_claims_without_relying_on_hashes(self):
        cases = [
            (0, lambda b: b['http']['http.json'].append(copy.deepcopy(b['http']['http.json'][0]))),
            (0, lambda b: b['http']['http.json'][0].update(status=200)),
            (1, lambda b: b['sources']['repositories'][-1].update(license='MIT')),
            (1, lambda b: b['sources']['repositories'][-1].update(revision='94b2e187b9fb6ab57d778bdfddbd235de8313d4c')),
            (2, lambda b: b['df_spec']['paths']['/api/v1/fut/prices']['get']['parameters'][1]['schema'].update(enum=['ps'])),
            (2, lambda b: b['findings']['providers'][1]['provider_description']['cost'].update(monthly=0)),
            (2, lambda b: b['findings']['providers'].pop()),
            (3, lambda b: b['findings']['providers'][1]['measured'].update(priced_card_count=22000)),
            (3, lambda b: b['findings']['providers'][0]['measured'].update(exact_mapping_verified=True)),
            (3, lambda b: b['findings']['measured'].update(sandbox_returned_platforms=['pc'])),
            (4, lambda b: b['findings']['measured'].update(successful_production_price_retrievals=1)),
            (4, lambda b: b['sandbox'].update(sandbox=False)),
            (5, lambda b: b['findings']['fallback']['coverage'].update(max_total_network_reads=7200)),
            (5, lambda b: b['findings']['fallback']['historical_measurement'].update(unique_auctions=52)),
            (5, lambda b: b['findings']['fallback'].update(allowed_operations=['search','buy'])),
        ]
        for criterion, change in cases:
            bad=copy.deepcopy(self.bundle);change(bad)
            self.assertIn(criterion,semantic_defects(bad),criterion)

    def test_collector_records_one_403_without_cookie_retention_or_retries(self):
        # Fixture exercises collection policy; it is not part of retained live evidence.
        url='https://example.test/manifest.json'
        error=urllib.error.HTTPError(url,403,'refused',
             {'Content-Type':'text/html','Set-Cookie':'private-value'},io.BytesIO(b'refused'))
        with tempfile.TemporaryDirectory() as tmp:
            out,private=Path(tmp)/'evidence',Path(tmp)/'private'
            opener=mock.Mock();opener.open.side_effect=error
            with mock.patch('urllib.request.build_opener',return_value=opener):
                capture([url],out,private)
            self.assertEqual(opener.open.call_count,1)
            row=json.loads((out/'http.json').read_bytes())['attempts'][0]
            self.assertEqual(row['status'],403)
            self.assertEqual(row['retry_count'],0)
            self.assertEqual(row['headers'],{'content-type':'text/html'})
            self.assertNotIn('private-value',(out/'http.json').read_text())
            request=opener.open.call_args.args[0]
            self.assertNotIn('Cookie',request.headers)
            self.assertNotIn('Authorization',request.headers)
            with self.assertRaises(FileExistsError): capture([url],out,private)
            self.assertEqual(opener.open.call_count,1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
