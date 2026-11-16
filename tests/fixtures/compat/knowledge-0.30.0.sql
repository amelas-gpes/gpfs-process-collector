-- Fictional compatibility fixture. Generated from the recorded release.
BEGIN;
CREATE TABLE canonical_aliases(canonical_id TEXT NOT NULL,alias TEXT NOT NULL,PRIMARY KEY(canonical_id,alias),FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id));
CREATE TABLE canonical_groups(id TEXT PRIMARY KEY,label TEXT NOT NULL,type TEXT NOT NULL,review_version INTEGER NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',stale_reason TEXT NOT NULL DEFAULT '');
CREATE TABLE canonical_history(id TEXT PRIMARY KEY,canonical_id TEXT NOT NULL,action TEXT NOT NULL,value TEXT NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,review_version INTEGER NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id));
CREATE TABLE canonical_members(canonical_id TEXT NOT NULL,entity_id TEXT NOT NULL UNIQUE,PRIMARY KEY(canonical_id,entity_id),FOREIGN KEY(canonical_id) REFERENCES canonical_groups(id),FOREIGN KEY(entity_id) REFERENCES entities(id));
CREATE TABLE deletions(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, process_id TEXT NOT NULL,
          revisions INTEGER NOT NULL, proposals INTEGER NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE edges(id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, type TEXT NOT NULL,
          status TEXT NOT NULL, submission_id TEXT NOT NULL, revision INTEGER NOT NULL, evidence TEXT NOT NULL);
INSERT INTO edges VALUES('2c6af7aa-a7ea-4195-aad5-44bac23377f0','a7e52592-4cce-405d-bf30-cd0ae6442554','6701c681-741f-495e-b5cf-96f5c9381b10','has_version','reported','2c326f72-1af5-4cd5-bb18-1f17750a5ecc',1,'{}');
INSERT INTO edges VALUES('52c03012-26db-4197-a356-20ab3a61ff26','6701c681-741f-495e-b5cf-96f5c9381b10','5df469ae-389e-4911-8207-377216c61563','contains','reported','2c326f72-1af5-4cd5-bb18-1f17750a5ecc',1,'{"step_id":"s1"}');
CREATE TABLE entities(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
          type TEXT NOT NULL, label TEXT NOT NULL, data TEXT NOT NULL);
INSERT INTO entities VALUES('a7e52592-4cce-405d-bf30-cd0ae6442554','2c326f72-1af5-4cd5-bb18-1f17750a5ecc',1,'process','Compatibility test','{"draft_edited":false,"draft_stale":false,"source":"draft"}');
INSERT INTO entities VALUES('6701c681-741f-495e-b5cf-96f5c9381b10','2c326f72-1af5-4cd5-bb18-1f17750a5ecc',1,'process_version','Compatibility test (revision 1)','{"draft_edited":false,"draft_stale":false,"source":"draft"}');
INSERT INTO entities VALUES('5df469ae-389e-4911-8207-377216c61563','2c326f72-1af5-4cd5-bb18-1f17750a5ecc',1,'step','Log the fictional ticket','{"_materialized_from":"draft","evidence_turns":["u1"],"id":"s1","title":"Log the fictional ticket","type":"activity"}');
CREATE TABLE jobs(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, owner_pid INTEGER,
          detail TEXT NOT NULL DEFAULT '',
          UNIQUE(submission_id,revision), FOREIGN KEY(submission_id,revision) REFERENCES revisions(submission_id,revision));
INSERT INTO jobs VALUES('96ad044c-8749-4e37-a9cd-fd9e353da492','2c326f72-1af5-4cd5-bb18-1f17750a5ecc',1,'pending',0,'','2026-11-16T04:26:12.930402+00:00',NULL,'');
CREATE TABLE private_documents(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, scope TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
CREATE TABLE private_meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE proposals(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, data TEXT NOT NULL,
          status TEXT NOT NULL, review_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, stale_reason TEXT NOT NULL DEFAULT '', claim_key TEXT);
CREATE TABLE review_history(id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, action TEXT NOT NULL,
          reviewer TEXT NOT NULL, reason TEXT NOT NULL, side TEXT, created_at TEXT NOT NULL, review_version INTEGER NOT NULL,
          FOREIGN KEY(proposal_id) REFERENCES proposals(id));
CREATE TABLE revisions(submission_id TEXT NOT NULL, process_id TEXT NOT NULL, revision INTEGER NOT NULL,
          payload TEXT NOT NULL, submitter TEXT, created_at TEXT NOT NULL, PRIMARY KEY(submission_id,revision), UNIQUE(process_id,revision));
INSERT INTO revisions VALUES('2c326f72-1af5-4cd5-bb18-1f17750a5ecc','86630409-8e77-41eb-80c4-1cd42d1d3224',1,'{"context":{"process_name":"Compatibility test"},"department":"","draft":{"connections":[],"steps":[{"evidence_turns":["u1"],"id":"s1","title":"Log the fictional ticket","type":"activity"}],"title":"Compatibility test"},"participant":"","scope":"","team":"","turns":[{"id":"u1","role":"user","text":"The fictional reviewer logs a ticket."}]}',NULL,'2026-11-16T04:26:12.929197+00:00');
CREATE TABLE status_capabilities(submission_id TEXT NOT NULL, revision INTEGER NOT NULL, token_hash TEXT NOT NULL, PRIMARY KEY(submission_id,revision));
CREATE TABLE submission_keys(key TEXT PRIMARY KEY, digest TEXT NOT NULL, principal TEXT, receipt TEXT NOT NULL, intent_digest TEXT);
CREATE INDEX canonical_history_group_idx ON canonical_history(canonical_id);
CREATE INDEX edges_endpoints_idx ON edges(source,target);
CREATE INDEX edges_target_idx ON edges(target);
CREATE INDEX entities_revision_type_idx ON entities(submission_id,revision,type);
CREATE INDEX proposals_claim_idx ON proposals(claim_key);
CREATE INDEX proposals_destination_idx ON proposals(json_extract(data,'$.destination_submission_id'),json_extract(data,'$.destination_revision'));
CREATE INDEX proposals_source_idx ON proposals(json_extract(data,'$.source_submission_id'),json_extract(data,'$.source_revision'));
CREATE INDEX review_history_proposal_idx ON review_history(proposal_id);
CREATE INDEX revisions_interview_idx ON revisions(json_extract(payload,'$.interview_id'));
CREATE INDEX revisions_order_idx ON revisions(created_at,submission_id,revision);
PRAGMA user_version=2;
COMMIT;
