# Approved bid-receipt repair: resume here

User approved the concrete plan in the current conversation, including one new
bounded live bid verification. This is not permission to replay either historical
950 command. The orchestrator task remains `obj-da182a175410/003-04`, BLOCKED;
all actors are stopped and the production service is read-only. Do not start a
second controller or recheck before the repair is tested/published/live-verified.
The orchestrator-policy enhancement IMP-004 remains deferred and is not in scope.

Read `AGENTS.md`, `checkpoint.json`, and `backup.json` first after interruption.
The checkpoint is mutable current-work state, not a sealed experiment verdict.
Keep completed live attempt evidence immutable. Before every live action consult
the durable attempt ledger; a lost reply/usage interruption never grants replay.

Starting main: `148d9a4`. Six pre-existing dirty 003-02 receipt files and the
untracked ack diagnosis/review lock were backed up; do not stage/discard them
as unrelated work. Backups use SQLite backup API and passed integrity checks.

Evidence/root cause:

- Complete user-reported Targets history: two Adeyemi, Cherki, Isak. Captured
  watched response matches those four. Current unconfirmed attempt is Alvarez
  definition 246191, command `6b3faed8a418890da8147b59eae039fc`.
- Earlier unconfirmed Doue definition 271421 command
  `ff4174653771149736e63b1ac12630f9` already has an operator LOST audit. Append
  the user's later non-registration clarification, do not rewrite that history.
- Actual current page checks native callback success/HTTP and ignores bid result
  items/stale marker. Python maps result.success directly to ACKNOWLEDGED.
- Captured public DAO bid keeps HTTP success with empty generated items, marks
  input stale, and emits ITEM_BID only if generated items exist. Item service
  still returns success and input-derived itemIds even with no DAO items.
- Correct offline reproduction: `private-captures/ack-diagnosis/offline-reproduction-v2.json`
  and `production-03/ack-diagnosis-01/REPORT.md`. The first exploratory reproduction
  had a wrongly oriented assignPropertyValues mock; use v2 only as valid proof.
  The actual historical wire bodies were discarded; never manufacture them.

Implementation decisions to carry forward:

1. Add optional archived / mandatory live `result.bid_receipt`, schema 1.
   Fields: schema, verdict, reason, wire_trade_id, wire_amount,
   wire_identity_matches, wire_amount_matches, wire_item_count, wire_error_code,
   native_success, native_error_code, native_error_name, native_item_count,
   matching_item_count, input_stale, auction. Strict enums/types, pseudonyms only.
2. Keep services.Item.bid as native invocation. Temporarily observe its exact
   transfersDao.bid observable, capturing only safe result fields and item tuple.
   Preserve observer semantics and restore in finally/timeouts; no extra request.
3. Before native send, match the private exact retained trade selector and the
   sole JSON body `{bid: amount}`. Reject mismatches before sending. Inspect only
   allowlisted response auctionInfo count/numeric error code, never headers/auth.
4. HTTP 200/empty is UNCONFIRMED, not REJECTED. ACCEPTED needs an actual matching
   native bid receipt showing account participation; old service itemIds are not
   proof. Native errors require a reviewed named code and no acceptance evidence.
5. Add typed REJECTED result. Retire a proven rejection with explicit audit and
   fresh account state. Opening rejection may release tentative slot; rejected
   rebid must retain prior valid participation. No auto-retry or fake LOST/refund.
6. Strict receipt required at live Store/Broker/Adapter boundaries; archive
   parser still reads old captured responses. Update actual native/Python test
   fixtures instead of exempting fixture mode from the live contract.
7. Broker permits validated ordinary rejection; unknown results still stop safely.
   Add operator NOT_REGISTERED clarification/resolution for the exact old commands
   using the user's supplied facts, separately from native proof.
8. Run relevant/full Python and all Node checks, preserve failures and genuine
   causes/fixes, commit/push before deployment. Native wire result fixtures are
   explicitly synthetic; don't call their success live proof.
9. Use a fresh page/extension with receipt capability verified by a zero-EA helper.
   One unique attempt, <=16 EA requests including discovery/pricing/account reads,
   <=1 bid, zero buys/moves/listings/maintenance, no duplicate or automatic retry.
   Preserve strategy maxBid=1000,minBuy=11000, pricing at most two calls, reserve,
   capacity, legal ticks and serialized pacing. Only an independently verified
   accepted account bid satisfies the positive live gate. Failure retains exact
   evidence and cannot silently consume another attempt.

No live attempt has started at the creation of this note. `checkpoint.json` is
authoritative for later progress. Production modifications are not yet complete.


Latest offline run: offline-03, 937 Python + 28 Node + five independent validators,
all PASS. Exact operator NOT_REGISTERED amendments have already been applied for
both historical commands; separate operator JSON files prove them. Do not apply
or replay them again. No native requests or new account mutations occurred.
The new harness module is `fc_access.actors_v1.verify_bid_receipt` (actor layer).
Its CLI requires --context context.json --journal canonical existing foundation
--checkpoint a new live-attempt.json --execute-authorized. It refuses an existing
ledger. Review current checkpoint/publication state before using it.
Windows focus initially failed; standard AttachThreadInput(current thread to
foreground and exact Edge window threads), BringWindowToTop and SetForegroundWindow
restored the verified official window without keyboard/mouse input. Detach both
thread pairs in finally. Current official window handle at that check: 1835972;
never assume a saved handle is still valid. ui.ps1 preflight-json then passed;
Home/Transfers markers were present, but actual EA authentication still requires
fresh native read evidence in the single new attempt.
