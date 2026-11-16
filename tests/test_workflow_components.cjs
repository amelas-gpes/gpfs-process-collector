"use strict";
// Fictional examples only. Run with: node tests/test_workflow_components.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../web/workflow-components.js"), "utf8"), {window});
const {all, resolve, forDisplay} = window.CollectorComponents;
const id = (title, fields = {}) => resolve({type: "activity", title, ...fields})?.id ?? null;
const examples = {
  capital_call:"Issue a capital call", investor_allocation:"Allocate proceeds among investors",
  waterfall:"Run the distribution waterfall", tax_withholding:"Calculate investor withholding",
  in_kind:"Distribute securities to investors", equalization:"Calculate equalization interest",
  fee_waiver:"Record a deemed contribution", special_profit:"Allocate special profits",
  partner_transfer:"Calculate the transfer split", investor_onboarding:"Create an investor profile",
  member_change:"Process a member departure", vesting:"Reallocate vested carry points",
  carry_recalculation:"Recalculate current-period carried interest", clawback:"Perform a clawback test",
  holdback:"Calculate the carry holdback", wind_down:"Wind down the carry vehicle",
  investment_setup:"Create a security master", loan_schedule:"Build a loan schedule",
  cash_interest:"Compute contractual cash interest", yield_calculation:"Calculate effective yield",
  pik_accrual:"Capitalize payment-in-kind interest", oid_amortization:"Amortize the original issue discount",
  warrant_valuation:"Allocate cost to the warrants", asset_valuation:"Determine the per-share value",
  security_conversion:"Convert convertible notes into shares",
  ledger_post:"Post a journal entry", dual_ledger:"Calculate the capital-interest ledger",
  reconciliation:"Reconcile opening cash balances", balance_rollforward:"Roll forward the prior balances",
  period_close:"Close the reporting period", variance_analysis:"Analyze material variances",
  revenue_recognition:"Recognize fee revenue", fee_calculation:"Calculate management fees",
  expense_allocation:"Allocate shared expenses", expense_transfer:"Record due-to-manager expenses",
  receivable:"Track outstanding receivables", invoice:"Register a vendor invoice",
  financial_statement:"Draft the income statement", expense_scrub:"Review expense coding",
  accrual:"Book an expense accrual", billing_exclusion:"Exclude nonbillable lines from invoices",
  cash_application:"Match a receipt to an investor", cash_classification:"Classify bank proceeds",
  payment_entry:"Enter the bank payment", wire_release:"Release vendor payments",
  callback:"Perform an independent callback", settlement:"Track payment settlement",
  liquidity:"Assess forward liquidity", facility_draw:"Prepare a facility draw request",
  facility_repayment:"Repay outstanding principal", borrowing_base:"Calculate borrowing-base capacity",
  bank_setup:"Activate the bank account", bank_mandate:"Refresh bank signatories",
  foreign_exchange:"Arrange foreign exchange", remittance_support:"Prepare withholding remittance support",
  population_lock:"Check investor eligibility", rule_lock:"Freeze the allocation rules",
  independent_review:"Conduct a second review", approval:"Request client authorization",
  kyc:"Perform KYC checks", exception:"Investigate identified discrepancies",
  audit_evidence:"Archive the audit evidence", access_control:"Revoke portal access",
  workbook_control:"Run workbook controls", ownership_trace:"Trace the ultimate beneficial owners",
  sanctions_screen:"Conduct watchlist screening", risk_rating:"Assign a case risk rating",
  covenant_check:"Test financial covenants", duplicate_check:"Check for duplicate invoices",
  blackline:"Review document blacklines", clean_copy:"Strip internal review marks",
  source_validation:"Verify source completeness", rule_confirmation:"Confirm the governing terms",
  event_setup:"Open the billing cycle", scope_setup:"Define the reporting scope",
  record_update:"Record the reason for the change", route_work:"Route the case to operations",
  status_monitor:"Report payment status", close_record:"Close the event record",
  calendar:"Build the execution calendar", document_pack:"Assemble the document package",
  workbook:"Prepare an allocation workbook", notice:"Draft investor notices",
  portal_release:"Publish the reporting package", handoff:"Accept the event handoff",
  data_migration:"Migrate legacy data into the target", data_mapping:"Map source fields",
  data_import:"Import transaction records", data_export:"Extract trial balances",
  audit_request:"Update the audit request log", reminder:"Send a payment reminder"
};
assert.equal(all.length, new Set(all.map(item => item.id)).size);
assert.deepEqual([...all.map(item => item.id)].sort(), Object.keys(examples).sort(), "Exercise every public design.");
for (const item of all) {
  assert.ok(item.label && item.family && item.description);
  assert.equal(id(examples[item.id]), item.id, examples[item.id]);
}

// Structural types survive. A document/store/subprocess can carry an instrument; checkpoints,
// gateways, waits and terminal events must not be reinterpreted as a business transaction.
assert.equal(id("Receive and register invoice", {type:"data_store"}), "invoice");
assert.equal(id("Prepare investor notices", {type:"document"}), "notice");
assert.equal(id("Archive the audit evidence", {type:"data_store"}), "audit_evidence");
assert.equal(id("Post a journal entry", {type:"subprocess"}), "ledger_post");
for (const type of ["start","end","wait","decision","parallel_split","parallel_join","merge","unrecognized"])
  assert.equal(id("Release the payment", {type}), null);

// These are different actions even though the nouns are similar.
for (const [title, expected] of [
  ["Authorize payment","approval"], ["Track payment status","status_monitor"],
  ["Prepare a payment","payment_entry"], ["Release payment","wire_release"],
  ["Record payment status","record_update"], ["Confirm and lock the waterfall rules","rule_lock"],
  ["Record the risk rating in the register","record_update"], ["Create the payment in the payment log","record_update"],
  ["Compare the historical source records to the expected amounts","source_validation"],
  ["Compare source records to the approved amounts","source_validation"],
  ["Submit the share-delivery instructions","in_kind"], ["Arrange foreign exchange (FX)","foreign_exchange"],
  ["Prepare and obtain clearance for a legal package","document_pack"],
  ["Create Northbank issuer and security master data","investment_setup"],
  ["Confirm the submitted W-8 signature and completeness","source_validation"],
  ["Review and approve the package","approval"], ["Generate and quality-check notices","notice"],
  ["Record the approved callback in the register","record_update"],
  ["File supporting evidence for a wire release","audit_evidence"],
  ["Track withheld tax for remittance","remittance_support"], ["Review PEP status","sanctions_screen"],
  ["Complete AML/KYC clearance","kyc"], ["Check available borrowing, covenants and deadlines","covenant_check"],
  ["Calculate or add investor withholding","tax_withholding"], ["Calculate carry from inception","carry_recalculation"],
  ["Review completed workbook","independent_review"], ["Calculate current-period carried interest","carry_recalculation"],
  ["Calculate carry points","vesting"], ["Prepare a bank mandate","bank_mandate"]
]) assert.equal(id(title), expected, title);

// Topic mentions, plans, negation, reported actions and another step's effects do not authorize
// a specialist image. In particular, an instruction file is not a released payment.
for (const title of [
  "Log in to the portal","Record retention review","Note holders meeting","Document review checklist","Tie a ribbon","Reconcile with the sponsor on the date","Decide whether to release wires","Do not release the payment","Release the payment?","Before posting, check the date",
  "How to calculate yield","Plan to migrate records","Review the plan to transfer securities","Await callback",
  "Prepare a payment release checklist","Prepare a wire report","Release a payment hold",
  "Send the payment to the reviewer","Release the payment for internal review",
  "Send payment instructions","Calculate an effective yield ceiling","Read the prior approval",
  "Review an invoice template","Prepare a callback log","Check whether a callback is needed",
  "Receive a payment release template","Review the memo about the prior step posting the journal entry",
  "Simulate a facility draw","Generate a proposed remittance support package","Process the handoff from the valuation team",
  "Record whether payment was released","Calculate a sample waiver","Check the requirement to approve a transfer"
]) assert.equal(id(title), null, title);
const detail = {actor:"Treasury analyst", description:"The Treasury analyst releases a payment."};
assert.equal(id("Step 4", detail), "wire_release");
assert.equal(id("Untitled step", {description:"Post the journal entry."}), "ledger_post");
assert.equal(id("Research the backlog", detail), null);
assert.equal(id("Step 4", {...detail, description:"The client released a payment earlier."}), null);
assert.equal(id("Step 4", {...detail, description:"The Treasury analyst does not release a payment."}), null);
assert.equal(id("Activity", {description:"The prior step releases a payment."}), null);
const evidenceOnly = {title:"Assemble the team",actor:"Wire release",system:"Bank payment release",
  inputs:"Approved wire", outputs:"Invoice issued",handoff:"Treasury releases payment",control_type:"approval"};
assert.equal(resolve(evidenceOnly), null);
assert.equal(resolve(null), null);
assert.equal(resolve({}), null);
const original = Object.freeze({type:"activity", title:"Release the payment"});
assert.equal(resolve(original), resolve(original));
for (const type of [undefined,"activity","subprocess","document","data_store"])
  assert.equal(forDisplay(Object.freeze({type,title:"Review the item"}), "risk_rating")?.id, "risk_rating");
assert.equal(forDisplay(original, "invented"), resolve(original));
assert.equal(forDisplay(original, "__proto__"), resolve(original));
assert.equal(forDisplay(original), resolve(original));
assert.equal(forDisplay({title:"Review item"}, {}), null);
for (const type of ["start","end","wait","decision","parallel_split","parallel_join","merge","unrecognized"])
  assert.equal(forDisplay({type,title:"Release the payment"}, "wire_release"), null);
assert.equal(forDisplay(null, "wire_release"), null);
console.log("Workflow component registry: " + all.length + " designs; direct actions, context exclusions and structural fallbacks passed.");
