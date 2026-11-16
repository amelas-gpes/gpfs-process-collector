-- Fictional compatibility fixture. Generated from the recorded release.
BEGIN;
CREATE TABLE canonical_aliases(canonical_id TEXT NOT NULL,alias TEXT NOT NULL,PRIMARY KEY(canonical_id,alias),FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id));
CREATE TABLE canonical_groups(id TEXT PRIMARY KEY,label TEXT NOT NULL,type TEXT NOT NULL,review_version INTEGER NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',stale_reason TEXT NOT NULL DEFAULT '');
CREATE TABLE canonical_history(id TEXT PRIMARY KEY,canonical_id TEXT NOT NULL,action TEXT NOT NULL,value TEXT NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,review_version INTEGER NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id));
CREATE TABLE canonical_members(canonical_id TEXT NOT NULL,entity_id TEXT NOT NULL UNIQUE,PRIMARY KEY(canonical_id,entity_id),FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id),FOREIGN KEY(entity_id) REFERENCES entities(id));
CREATE TABLE edges(id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, type TEXT NOT NULL,
          status TEXT NOT NULL, submission_id TEXT NOT NULL, revision INTEGER NOT NULL, evidence TEXT NOT NULL);
INSERT INTO edges VALUES('907b5ed3-2e75-42a0-a8ef-1e7b9fef1e4b','f53f24e0-0db1-4003-85b6-c68ef7d045e1','2be0243e-6b79-4e58-92ee-0e34654aa561','has_version','reported','c7ca6c0c-3b7f-4e0d-89d6-f82b03136fe7',1,'{}');
INSERT INTO edges VALUES('cf4b6e88-5666-4782-8e7e-8c0a13c36f50','2be0243e-6b79-4e58-92ee-0e34654aa561','412e5bf5-1368-4fae-bb92-fa9f254b43ee','contains','reported','c7ca6c0c-3b7f-4e0d-89d6-f82b03136fe7',1,'{"step_id":"s1"}');
CREATE TABLE entities(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
          type TEXT NOT NULL, label TEXT NOT NULL, data TEXT NOT NULL);
INSERT INTO entities VALUES('f53f24e0-0db1-4003-85b6-c68ef7d045e1','c7ca6c0c-3b7f-4e0d-89d6-f82b03136fe7',1,'process','Compatibility test','{"source":"draft"}');
INSERT INTO entities VALUES('2be0243e-6b79-4e58-92ee-0e34654aa561','c7ca6c0c-3b7f-4e0d-89d6-f82b03136fe7',1,'process_version','Compatibility test (revision 1)','{"source":"draft"}');
INSERT INTO entities VALUES('412e5bf5-1368-4fae-bb92-fa9f254b43ee','c7ca6c0c-3b7f-4e0d-89d6-f82b03136fe7',1,'step','Log the fictional ticket','{"_materialized_from":"draft","evidence_turns":["u1"],"id":"s1","title":"Log the fictional ticket","type":"activity"}');
CREATE TABLE jobs(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, owner_pid INTEGER,
          UNIQUE(submission_id,revision), FOREIGN KEY(submission_id,revision) REFERENCES revisions(submission_id,revision));
INSERT INTO jobs VALUES('06ff31a5-e964-466c-b522-cd058bcfaa5d','c7ca6c0c-3b7f-4e0d-89d6-f82b03136fe7',1,'pending',0,'','2026-11-16T04:26:12.415345+00:00',NULL);
CREATE TABLE private_documents(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, scope TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
CREATE TABLE private_meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE proposals(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, data TEXT NOT NULL,
          status TEXT NOT NULL, review_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, stale_reason TEXT NOT NULL DEFAULT '', claim_key TEXT);
CREATE TABLE review_history(id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, action TEXT NOT NULL,
          reviewer TEXT NOT NULL, reason TEXT NOT NULL, side TEXT, created_at TEXT NOT NULL, review_version INTEGER NOT NULL,
          FOREIGN KEY(proposal_id) REFERENCES proposals(id));
CREATE TABLE revisions(submission_id TEXT NOT NULL, process_id TEXT NOT NULL, revision INTEGER NOT NULL,
          payload TEXT NOT NULL, submitter TEXT, created_at TEXT NOT NULL, PRIMARY KEY(submission_id,revision), UNIQUE(process_id,revision));
INSERT INTO revisions VALUES('c7ca6c0c-3b7f-4e0d-89d6-f82b03136fe7','f384da0e-8205-46ad-a8bf-bb5087df82fc',1,'{"context":{"process_name":"Compatibility test"},"department":"","draft":{"connections":[],"steps":[{"evidence_turns":["u1"],"id":"s1","title":"Log the fictional ticket","type":"activity"}],"title":"Compatibility test"},"participant":"","scope":"","team":"","turns":[{"id":"u1","role":"user","text":"The fictional reviewer logs a ticket."}]}',NULL,'2026-11-16T04:26:12.415345+00:00');
CREATE TABLE status_capabilities(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, token_hash TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
CREATE TABLE submission_keys(key TEXT PRIMARY KEY, digest TEXT NOT NULL, principal TEXT, receipt TEXT NOT NULL, intent_digest TEXT);
CREATE INDEX canonical_history_group_idx ON canonical_history(canonical_id);
CREATE INDEX edges_endpoints_idx ON edges(source,target);
CREATE INDEX entities_revision_type_idx ON entities(submission_id,revision,type);
CREATE INDEX proposals_claim_idx ON proposals(claim_key);
CREATE INDEX proposals_destination_idx ON proposals(json_extract(data,'$.destination_submission_id'),json_extract(data,'$.destination_revision'));
CREATE INDEX proposals_source_idx ON proposals(json_extract(data,'$.source_submission_id'),json_extract(data,'$.source_revision'));
CREATE INDEX review_history_proposal_idx ON review_history(proposal_id);
CREATE INDEX revisions_order_idx ON revisions(created_at,submission_id,revision);
PRAGMA user_version=0;
COMMIT;
