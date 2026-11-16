-- DESIGN FIXTURE ONLY: execute in a new temporary SQLite database, never live.
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE c1_meta(version INTEGER PRIMARY KEY CHECK(version=1));
INSERT INTO c1_meta VALUES(1);
CREATE TABLE c1_controllers(
 scope TEXT PRIMARY KEY, owner TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>0),
 phase TEXT NOT NULL CHECK(phase IN ('ACQUIRING','MANAGING')),
 lifecycle TEXT NOT NULL CHECK(lifecycle IN ('STOPPED','RUNNING','PAUSED','HALTED')),
 reason TEXT, config_json TEXT NOT NULL CHECK(json_valid(config_json)));
CREATE TABLE c1_observations(
 id TEXT PRIMARY KEY, scope TEXT NOT NULL REFERENCES c1_controllers(scope),
 kind TEXT NOT NULL, observed_at TEXT NOT NULL, network_at TEXT, document_epoch TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('native','fixture')),
 complete INTEGER NOT NULL CHECK(complete IN (0,1)),
 safe_json TEXT NOT NULL CHECK(json_valid(safe_json)));
CREATE TABLE c1_batches(
 id TEXT PRIMARY KEY, scope TEXT NOT NULL REFERENCES c1_controllers(scope),
 created_at TEXT NOT NULL, completed_at TEXT, state TEXT NOT NULL,
 credits_read TEXT REFERENCES c1_observations(id), discovery_read TEXT REFERENCES c1_observations(id),
 inventory_read TEXT REFERENCES c1_observations(id), config_json TEXT NOT NULL CHECK(json_valid(config_json)));
CREATE TABLE c1_quotes(
 id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES c1_batches(id),
 definition_id INTEGER NOT NULL CHECK(definition_id>0), observed_at TEXT NOT NULL,
 resale_bin INTEGER NOT NULL CHECK(resale_bin>0), cap INTEGER NOT NULL CHECK(cap>0 AND cap<resale_bin),
 evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)));
CREATE TABLE c1_candidates(
 batch_id TEXT NOT NULL REFERENCES c1_batches(id), ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 10),
 trade_id TEXT NOT NULL, item_id TEXT NOT NULL, definition_id INTEGER NOT NULL CHECK(definition_id>0),
 quote_id TEXT NOT NULL REFERENCES c1_quotes(id), observation_id TEXT NOT NULL REFERENCES c1_observations(id),
 selected_at TEXT NOT NULL, auction_deadline TEXT NOT NULL, minimum_bid INTEGER NOT NULL CHECK(minimum_bid>0),
 PRIMARY KEY(batch_id,trade_id), UNIQUE(batch_id,ordinal), UNIQUE(batch_id,item_id));
CREATE TABLE c1_commands(
 id TEXT PRIMARY KEY, scope TEXT NOT NULL REFERENCES c1_controllers(scope),
 batch_id TEXT NOT NULL REFERENCES c1_batches(id), operation TEXT NOT NULL,
 trade_id TEXT, item_id TEXT, definition_id INTEGER, amount INTEGER CHECK(amount>0),
 action_key TEXT NOT NULL UNIQUE, decision_observation TEXT NOT NULL REFERENCES c1_observations(id),
 owner_generation INTEGER NOT NULL, intended_at TEXT NOT NULL, deadline TEXT NOT NULL,
 claimed_at TEXT, state TEXT NOT NULL CHECK(state IN ('INTENDED','CLAIMED','RETURNED','UNKNOWN','NOT_SENT')));
CREATE TABLE c1_tombstones(
 action_key TEXT PRIMARY KEY, command_id TEXT NOT NULL UNIQUE REFERENCES c1_commands(id),
 consumed_at TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE c1_results(
 seq INTEGER PRIMARY KEY, command_id TEXT NOT NULL REFERENCES c1_commands(id), at TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('ACCEPTED','REJECTED','UNCONFIRMED','NOT_SENT','INDEPENDENT')),
 observation_id TEXT REFERENCES c1_observations(id), safe_json TEXT NOT NULL CHECK(json_valid(safe_json)));
CREATE TABLE c1_membership(
 batch_id TEXT NOT NULL, trade_id TEXT NOT NULL, scope TEXT NOT NULL REFERENCES c1_controllers(scope),
 ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 10), proof_read TEXT NOT NULL REFERENCES c1_observations(id),
 confirmed_state TEXT NOT NULL CHECK(confirmed_state IN ('highest','outbid')),
 terminal_state TEXT CHECK(terminal_state IN ('LOST','WON_OWNED_PAID')),
 next_deadline TEXT NOT NULL, PRIMARY KEY(batch_id,trade_id), UNIQUE(batch_id,ordinal),
 FOREIGN KEY(batch_id,trade_id) REFERENCES c1_candidates(batch_id,trade_id));
CREATE UNIQUE INDEX c1_active_membership ON c1_membership(scope,trade_id) WHERE terminal_state IS NULL;
CREATE TABLE c1_transitions(
 seq INTEGER PRIMARY KEY, scope TEXT NOT NULL REFERENCES c1_controllers(scope), batch_id TEXT REFERENCES c1_batches(id),
 at TEXT NOT NULL, from_phase TEXT NOT NULL CHECK(from_phase IN ('ACQUIRING','MANAGING')),
 to_phase TEXT NOT NULL CHECK(to_phase IN ('ACQUIRING','MANAGING')), reason TEXT NOT NULL);
CREATE TABLE c1_deadlines(
 scope TEXT NOT NULL REFERENCES c1_controllers(scope), kind TEXT NOT NULL, entity_id TEXT NOT NULL,
 due_at TEXT NOT NULL, observation_id TEXT REFERENCES c1_observations(id),
 PRIMARY KEY(scope,kind,entity_id));
CREATE TABLE c1_resales(
 item_id TEXT PRIMARY KEY, scope TEXT NOT NULL REFERENCES c1_controllers(scope), batch_id TEXT NOT NULL REFERENCES c1_batches(id),
 trade_id TEXT NOT NULL, ownership_read TEXT NOT NULL REFERENCES c1_observations(id), paid INTEGER NOT NULL CHECK(paid>0),
 quote_id TEXT NOT NULL REFERENCES c1_quotes(id), state TEXT NOT NULL, listing_command TEXT REFERENCES c1_commands(id));
CREATE TABLE c1_probe_windows(
 checkpoint TEXT PRIMARY KEY, scope TEXT NOT NULL REFERENCES c1_controllers(scope),
 question TEXT NOT NULL, expires_at TEXT NOT NULL, max_requests INTEGER NOT NULL CHECK(max_requests>=0),
 max_mutations INTEGER NOT NULL CHECK(max_mutations>=0),
 consumed_requests INTEGER NOT NULL DEFAULT 0 CHECK(consumed_requests BETWEEN 0 AND max_requests),
 consumed_mutations INTEGER NOT NULL DEFAULT 0 CHECK(consumed_mutations BETWEEN 0 AND max_mutations),
 state TEXT NOT NULL CHECK(state IN ('PREPARED','CLAIMED','CLOSED','INTERRUPTED')), cleanup_json TEXT CHECK(json_valid(cleanup_json)));
CREATE TRIGGER c1_no_replay BEFORE UPDATE OF state ON c1_commands
 WHEN OLD.state!='INTENDED' AND NEW.state='INTENDED'
 BEGIN SELECT RAISE(ABORT,'consumed_command'); END;
CREATE TRIGGER c1_command_no_delete BEFORE DELETE ON c1_commands BEGIN SELECT RAISE(ABORT,'durable_intent'); END;
CREATE TRIGGER c1_intent_immutable BEFORE UPDATE OF id,scope,batch_id,operation,trade_id,item_id,definition_id,amount,action_key,decision_observation,owner_generation,intended_at,deadline ON c1_commands
 BEGIN SELECT RAISE(ABORT,'immutable_intent'); END;
CREATE TRIGGER c1_quote_no_update BEFORE UPDATE ON c1_quotes BEGIN SELECT RAISE(ABORT,'stored_policy'); END;
CREATE TRIGGER c1_quote_no_delete BEFORE DELETE ON c1_quotes BEGIN SELECT RAISE(ABORT,'stored_policy'); END;
CREATE TRIGGER c1_probe_no_reset BEFORE UPDATE OF consumed_requests,consumed_mutations ON c1_probe_windows
 WHEN NEW.consumed_requests<OLD.consumed_requests OR NEW.consumed_mutations<OLD.consumed_mutations
 BEGIN SELECT RAISE(ABORT,'consumed_budget'); END;
CREATE TRIGGER c1_probe_budget_immutable BEFORE UPDATE OF checkpoint,scope,question,expires_at,max_requests,max_mutations ON c1_probe_windows
 BEGIN SELECT RAISE(ABORT,'immutable_window'); END;
CREATE TRIGGER c1_probe_no_delete BEFORE DELETE ON c1_probe_windows BEGIN SELECT RAISE(ABORT,'consumed_window'); END;
CREATE TRIGGER c1_tombstone_no_delete BEFORE DELETE ON c1_tombstones BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER c1_tombstone_no_update BEFORE UPDATE ON c1_tombstones BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER c1_result_no_delete BEFORE DELETE ON c1_results BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER c1_result_no_update BEFORE UPDATE ON c1_results BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER c1_observation_no_update BEFORE UPDATE ON c1_observations BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER c1_observation_no_delete BEFORE DELETE ON c1_observations BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER c1_transition_no_update BEFORE UPDATE ON c1_transitions BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER c1_transition_no_delete BEFORE DELETE ON c1_transitions BEGIN SELECT RAISE(ABORT,'append_only'); END;
-- Runtime authority must additionally enforce scope/epoch agreement between FK
-- records, independent authenticated proof, legality, complete inventory validity,
-- claim+tombstone atomicity and one live owner. SQL alone grants no write power.
