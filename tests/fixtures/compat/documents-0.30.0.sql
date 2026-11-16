-- Fictional compatibility fixture. Generated from the recorded release.
BEGIN;
CREATE TABLE chunk_map (scope TEXT NOT NULL, document_id TEXT NOT NULL, id TEXT NOT NULL, chunk_rowid INTEGER NOT NULL, ordinal INTEGER, PRIMARY KEY (scope, document_id, id)) WITHOUT ROWID;
INSERT INTO chunk_map VALUES('e87b724453047947fe6328f30ff6b827f688cbc49a2351cb7cceb0a67d10413e','doc_111111111111111111111111','doc_111111111111111111111111_s1_r1_2_b1_c1',1,256);
CREATE VIRTUAL TABLE chunks USING fts5(id UNINDEXED, document_id UNINDEXED, scope, label, text, location UNINDEXED, tokenize='unicode61');
INSERT INTO chunks VALUES('doc_111111111111111111111111_s1_r1_2_b1_c1','doc_111111111111111111111111','e87b724453047947fe6328f30ff6b827f688cbc49a2351cb7cceb0a67d10413e','fixture.csv · CSV!A1:B2','A1=Ticket | B1=Action
A2=Fixture | B2=Record','{"sheet": "CSV", "sheet_index": 1, "range": "A1:B2", "row_start": 1, "row_end": 2, "header_sample": "A1=Ticket | B1=Action", "cell_lengths": [9, 9, 10, 9]}');
CREATE TABLE documents (id TEXT PRIMARY KEY, scope TEXT NOT NULL, record TEXT NOT NULL);
INSERT INTO documents VALUES('doc_111111111111111111111111','e87b724453047947fe6328f30ff6b827f688cbc49a2351cb7cceb0a67d10413e','{"id": "doc_111111111111111111111111", "name": "fixture.csv", "filename": "fixture.csv", "kind": "csv", "media_type": "text/csv", "size": 29, "sha256": "65bfecf2fade5ed15007e85baa3483352b67e8f64d8939224f036196f5a5c185", "status": "ready", "archived": false, "created_at": 1794803172.864286, "updated_at": 1794803172.9026294, "context": {}, "inventory": {"sheets": [{"name": "CSV", "index": 1, "rows": 2, "columns": 2, "header_sample": "A1=Ticket | B1=Action", "header_sample_truncated": false, "populated_cells": 4, "formula_cells": 0, "formulas_without_cached_values": 0}], "sheet_count": 1, "rows": 2, "delimiter": ",", "formula_policy": "CSV cells are literal text; formulas are never executed."}, "coverage": {"indexed_units": 2, "total_units": 2, "limitations": []}, "chunk_count": 1, "error": null, "analysis": {}, "revision": 2, "extraction_version": 3, "extraction_needs_reindex": false, "visual_transcription_hashes": {}}');
CREATE TABLE scopes (scope TEXT PRIMARY KEY, created REAL NOT NULL);
INSERT INTO scopes VALUES('e87b724453047947fe6328f30ff6b827f688cbc49a2351cb7cceb0a67d10413e',1794803172.864286);
CREATE INDEX chunk_map_id ON chunk_map(scope, id);
CREATE INDEX chunk_map_order ON chunk_map(scope, document_id, chunk_rowid);
CREATE INDEX chunk_map_ordinal ON chunk_map(scope,document_id,ordinal);
CREATE INDEX document_scope ON documents(scope);
PRAGMA user_version=3;
COMMIT;
