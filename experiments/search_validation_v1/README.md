# 001c-04 bounded read adapter

Results and limitations: [REPORT.md](../../docs/research/001c/001c-04/REPORT.md).
Do not bid from a retained snapshot. No account-write endpoint exists here.

Final loopback service: 127.0.0.1:8778. Check `/health` before starting
`python -m experiments.search_validation_v1.server`. The reviewed extension is
`browser/`, version 0.3.0, ID coofofjomkjpjbojdkamapbfbcjkpmhn. Attach on the
verified official EA Web App tab. Preserve the existing budget and prior outputs.
Current experiment is finished with nine deliveries consumed; these are
reproduction contracts, not instructions to replay completed captures.

An explicitly scoped fresh read, if authorized in a subsequent task, uses:

```
python -m experiments.search_validation_v1 --output NEW.json --max-bid 1000 --min-buy 10500
python -m experiments.search_validation_v1 --output NEW-EXACT.json --definition-id 227323 --max-buy 10000
python -m experiments.search_validation_v1 --output NEW-CAPS.json --definition-id 227323 --max-bid 1000 --min-buy 10500 --with-caps
```

Each new basename must not exist. Page is 1 or 2; count is 21. `--with-caps`
requires an exact definition and permits one additional native price-limit GET.
The twelve-delivery ceiling persists before dispatch; the host rejects commands
inside 31 seconds of the last delivered command. No automatic retry is allowed.
The page requires official HTTPS EA, accepted PC persona and a 30-second guard.
No credentials or raw item/trade identifiers leave the page. Local correlations
and numeric public game telemetry are not authentication material.

`validation.assess` verifies observed DTO -> query mapping (maxBid/macr,
minBuy/minb, maxBuy/maxb, defId/definitionId), independent wire/entity identity
and bid/BIN semantics. `availability` returns bounded absence/change/stale states.
`economics.evaluate` uses fresh exact-version PC asks and native caps, rejects
unsupported/old inputs and returns an indicative cap with no bid authorization.
Native client ticks and server tick acceptance have separate evidence levels.
