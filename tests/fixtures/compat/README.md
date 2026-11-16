# Saved-interview and SQLite compatibility fixtures

All records describe a fictional ticket and a fictional register. Each JSON file came from running the named version's `web/app.js` session exporter in an offline Node VM. The inputs include one question, one participant answer, a working summary, and an unknown finding for each topic the version supported.

| Layout | Source revision |
| --- | --- |
| 0.25.1, eleven topics | 771655a802f9a5700482858f55c20219d362d8a5 |
| 0.26.1 | 179781a328021e5ec05078e2959f289f2bde2790 |
| 0.29.0 | 9d630f265591d761ece72e53c70a30fe57c90013 |
| 0.30.0 | Source tree accompanying these fixtures |

For the 0.26.1 and 0.30.0 stores, each version's DocumentStore attached and extracted a two-row CSV. Its KnowledgeGraph filed a synthetic process with one cited step. Each SQL file preserves that store's table and index definitions, format number and fictional records. Loading the SQL recreates SQLite's own FTS structures. Private authentication metadata, receipt hashes and deduplication entries are excluded. The test uses a fresh temporary store and exercises the status capability returned for a new revision.

To add a release fixture, use its exporter and store writers with the same input in an empty temporary directory. Dump the application tables and indexes as SQL. Omit SQLite internal and FTS shadow data. Retain any chunk row IDs referenced by the published index and record the SQLite user_version. Check the JSON and SQL as text before committing. The document original is the literal CSV in test_release_compatibility.py.

A current build opens the older save with provisional coverage. A document indexed by 0.26.1 stays readable by its original source ID and is marked for an extraction check.
