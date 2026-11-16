/* Local process instruments. The diagram data, controls and captured facts remain authoritative. */
"use strict";
(function (scope) {
  // Each instrument describes an action, never an observed outcome. Nothing is loaded or generated on demand.
  const catalog = {
    Capital: [
      ["capital_call", "Capital call", "Prepare or issue a request for investors to contribute capital."],
      ["investor_allocation", "Investor allocation", "Divide an event or fund amount among its participants."],
      ["waterfall", "Distribution waterfall", "Calculate the order and amount of distributions across tiers."],
      ["tax_withholding", "Tax withholding", "Work out the tax to retain from an investor payment."],
      ["in_kind", "In-kind distribution", "Assign or deliver securities or other assets to investors instead of cash."],
      ["equalization", "Close equalization", "Calculate compensation or rebalance interests when investors enter at a later close."],
      ["fee_waiver", "Fee waiver", "Apply a waived fee or record the associated deemed contribution."],
      ["special_profit", "Special profit allocation", "Calculate or assign the income shift provided for by a special-profits arrangement."],
      ["partner_transfer", "Partner transfer", "Split and move an existing partner interest between its old and new holders."],
      ["investor_onboarding", "Investor setup", "Open an onboarding record or create an investor profile for administration."],
      ["member_change", "Member change", "Apply a member admission, departure or related commitment change."],
      ["vesting", "Carry points and vesting", "Calculate earned carry points or redistribute points among members."],
      ["carry_recalculation", "Carry income test", "Calculate or independently test carried interest across periods, including the current-period change."],
      ["clawback", "Clawback test", "Determine whether earlier distributions create an obligation to return carry."],
      ["holdback", "Carry holdback", "Calculate, retain or release the reserved portion of carry."],
      ["wind_down", "Vehicle wind-down", "Wind down a vehicle or check that final partner capital has reached zero."]
    ],
    Investments: [
      ["investment_setup", "Investment setup", "Open a purchase record or set up the issuer, security or lot in investment records."],
      ["loan_schedule", "Loan schedule", "Build the contractual sequence of loan balances, dates and payments."],
      ["cash_interest", "Cash interest", "Calculate the interest payable in cash under the loan terms."],
      ["yield_calculation", "Investment yield", "Calculate an investment return or effective yield over time."],
      ["pik_accrual", "Payment-in-kind interest", "Calculate interest added to loan principal instead of paid in cash."],
      ["oid_amortization", "Discount amortization", "Spread a loan discount or the applicable allocated cost over its term."],
      ["warrant_valuation", "Warrant cost allocation", "Assign or record the supported portion of investment cost attributable to warrants."],
      ["asset_valuation", "Asset valuation", "Determine the value of a security or in-kind distribution using the applicable price and basis."],
      ["security_conversion", "Security conversion", "Convert an existing instrument to a new interest under its executed terms."]
    ],
    Accounting: [
      ["ledger_post", "Ledger posting", "Post a transaction or journal entry to the accounting ledger."],
      ["dual_ledger", "Capital and carry ledgers", "Calculate the capital-interest or carry-interest side of a member allocation."],
      ["reconciliation", "Reconciliation", "Compare balances or records across sources and account for differences."],
      ["balance_rollforward", "Roll-forward", "Carry a prior period's balances or working model into a new period."],
      ["period_close", "Period close", "Complete the accounting close for a defined reporting period."],
      ["variance_analysis", "Variance analysis", "Examine movements or differences and investigate their drivers."],
      ["revenue_recognition", "Revenue recognition", "Recognize earned revenue in its applicable period."],
      ["fee_calculation", "Fee calculation", "Calculate a fee, catch-up, offset or related adjustment."],
      ["expense_allocation", "Expense allocation", "Distribute an expense among funds, entities or cost categories."],
      ["expense_transfer", "Due-to-manager transfer", "Record costs paid by the manager for another entity in that entity's books."],
      ["receivable", "Receivable tracking", "Establish, age or monitor amounts due from another party."],
      ["invoice", "Invoice processing", "Create, log, enter or transmit an invoice."],
      ["financial_statement", "Financial statement", "Prepare a statement, disclosure or footnote for financial reporting."],
      ["expense_scrub", "Expense review", "Inspect individual expense lines, coding or offsetting charges before billing."],
      ["accrual", "Accrual", "Calculate or record a period accrual for an amount not yet settled."],
      ["billing_exclusion", "Billing exclusion", "Separate nonbillable expense lines from what is charged while preserving the underlying record."]
    ],
    Treasury: [
      ["cash_application", "Receipt matching", "Identify a receipt and match or apply it to the right investor or outstanding item."],
      ["cash_classification", "Cash classification", "Classify proceeds, cash sources or cash uses in the working schedules."],
      ["payment_entry", "Payment preparation", "Create the payment instruction or enter it for bank authorization."],
      ["wire_release", "Payment release", "Release a payment instruction through the bank or payment channel."],
      ["callback", "Callback verification", "Make the independent callback used to verify payment instructions."],
      ["settlement", "Settlement tracking", "Track the bank or custodian's final status for a transaction."],
      ["liquidity", "Liquidity assessment", "Assess cash available for current or expected outflows."],
      ["facility_draw", "Facility draw", "Prepare a draw request or draw funds against a credit facility."],
      ["facility_repayment", "Facility repayment", "Determine or repay principal and interest on a borrowing."],
      ["borrowing_base", "Borrowing base", "Calculate borrowing capacity against eligible collateral or commitments."],
      ["bank_setup", "Bank account setup", "Establish, activate or update a bank account."],
      ["bank_mandate", "Bank mandate", "Prepare, refresh or verify the account mandate and its authorized signatories."],
      ["foreign_exchange", "Foreign exchange", "Arrange a currency conversion for a payment or cash requirement."],
      ["remittance_support", "Tax remittance support", "Track withheld tax or send its supporting records to the party responsible for remittance."]
    ],
    Assurance: [
      ["population_lock", "Population control", "Check or freeze the population included in a calculation or event."],
      ["rule_lock", "Method lock", "Freeze the governing calculation rules or method for a run."],
      ["independent_review", "Review checkpoint", "Perform an identified internal, independent, manager or client review."],
      ["approval", "Authorization", "Request or give authorization for the captured action."],
      ["kyc", "Identity and screening", "Perform identity, ownership, due diligence or sanctions checks."],
      ["exception", "Exception handling", "Investigate, escalate or resolve an identified exception."],
      ["audit_evidence", "Evidence filing", "Collect, file or retain support for a record, review or audit."],
      ["access_control", "Access control", "Set up, change, test or remove access for a user or recipient."],
      ["workbook_control", "Workbook controls", "Run, repeat or validate internal checks across a workbook."],
      ["source_validation", "Source validation", "Inspect a source record or compare details against a reference for completeness, consistency or validity."],
      ["rule_confirmation", "Rule confirmation", "Consult or confirm the governing terms or method before applying them."],
      ["ownership_trace", "Beneficial ownership", "Trace the people or entities that ultimately own or control an entity."],
      ["sanctions_screen", "Watchlist screening", "Screen identities against sanctions, politically exposed person or adverse-media sources."],
      ["risk_rating", "Risk assessment", "Assign a risk classification using the applicable model and case facts."],
      ["covenant_check", "Covenant check", "Compare facility measures and dates with their contractual limits."],
      ["duplicate_check", "Duplicate detection", "Check for repeated invoices, payments or records before processing."],
      ["blackline", "Document comparison", "Compare versions to identify additions, removals or presentation changes."],
      ["clean_copy", "External copy cleanup", "Remove internal marks or restricted content from a copy intended for an external recipient."]
    ],
    Delivery: [
      ["event_setup", "Event intake", "Open a process event or cycle and establish its working record."],
      ["scope_setup", "Scope and responsibility", "Set the scope of work or identify who is responsible for it."],
      ["record_update", "Record maintenance", "Capture or update information in a register, schedule or other working record."],
      ["route_work", "Case routing", "Identify a route and direct work to the appropriate party or procedure."],
      ["status_monitor", "Status tracking", "Observe or report an existing status, milestone or open item."],
      ["close_record", "Case closure", "Close or archive the record of an event or case."],
      ["calendar", "Execution calendar", "Set dates, deadlines or restrictions on the event calendar."],
      ["document_pack", "Document assembly", "Gather or prepare a set of documents for a defined purpose."],
      ["workbook", "Workbook preparation", "Create, update or link the working schedules in a workbook."],
      ["notice", "Investor notices", "Prepare, check or send the notices communicating an investor event."],
      ["portal_release", "Portal publication", "Publish a package, notice or campaign through its delivery channel."],
      ["handoff", "Work handoff", "Pass work to the next responsible party or accept it from the prior one."],
      ["data_migration", "System migration", "Move a dataset from its source system into a target environment."],
      ["data_mapping", "Field mapping", "Build or apply a crosswalk between source fields, codes and target values."],
      ["data_import", "Data import", "Load records or a prepared file into the receiving system."],
      ["data_export", "Data extraction", "Extract ledger detail, balances or other source data for further use."],
      ["audit_request", "Audit request tracking", "Log, maintain or close requests for information from auditors."],
      ["reminder", "Follow-up reminder", "Send a reminder for an outstanding response, payment or action."]
    ]
  };
  const all = Object.freeze(Object.entries(catalog).flatMap(([family, rows]) =>
    rows.map(([id, label, description]) => Object.freeze({id, label, family, description}))));
  const byId = new Map(all.map(item => [item.id, item]));

  // Anchored verb + direct object pairs, ordered from narrow operations to general ones.
  // The object cannot float past a verb or a clause to find a convenient keyword.
  // A named operation is also allowed when it is the *entire* title.
  const rules = [];
  const exact = new Map();
  const verbs = new Map();
  function action(id, verbList, object, names = []) {
    const choices = verbList.split("|");
    for (const verb of choices.filter(v => /^[a-z]+$/.test(v))) {
      const third = verb.endsWith("y") && !/[aeiou]y$/.test(verb) ? verb.slice(0, -1) + "ies"
        : /(?:o|s|sh|ch|x|z)$/.test(verb) ? verb + "es" : verb + "s";
      verbs.set(verb, verb);
      verbs.set(third, verb);
    }
    rules.push({id, match: new RegExp("^(?:" + verbList + ") (?:(?:the|a|an|each|any|all|new|current|approved|final|controlled|draft) )*(?:" + object + ")\\b")});
    for (const name of names) exact.set(name, id);
  }
  action("waterfall", "calculate|run|model|recalculate|execute|build", "(?:(?:cash|distribution|fund specific|carried interest|carry) )?waterfall", ["waterfall calculation", "distribution waterfall calculation"]);
  action("tax_withholding", "calculate|compute|apply|add|determine", "(?:investor |tax |investor tax )?withholding", ["withholding calculation", "tax withholding calculation"]);
  action("fee_waiver", "apply|record|recognize|calculate", "(?:fee waivers?|waived (?:management )?fees?|deemed contributions?)", ["deemed contribution recording"]);
  action("special_profit", "calculate|allocate|record|recalculate", "special profits?", ["special profit allocation"]);
  action("equalization", "calculate|allocate|compute|apply|prepare", "(?:(?:lpa|investor|close) )?(?:equalization|equalisation)(?: (?:interest|amounts?|capital call|payment|allocation))?", ["equalization interest calculation", "equalisation interest calculation"]);
  action("equalization", "rebalance", "(?:future )?(?:commitments?|ownership percentages|investor interests)");
  action("equalization", "calculate", "as if participation(?: for (?:the )?subsequent close)?");
  action("capital_call", "issue|prepare|execute|initiate|launch|make", "(?:investor )?(?:capital calls?|call for capital)", ["capital call issuance"]);
  action("in_kind", "distribute|allocate|deliver|transfer", "(?:(?:eligible|investor|whole|restricted) )?(?:shares|securities|lots in kind|assets in kind)", ["distribution in kind", "in kind distribution", "securities delivery"]);
  action("in_kind", "execute|prepare", "(?:in kind distribution|distribution in kind)");
  action("in_kind", "submit|send", "(?:share|securities) delivery instructions");
  action("partner_transfer", "calculate|apply|execute|process|record|prepare", "(?:(?:partner|investor|ownership) (?:interest )?transfers?|transfer split|transfer of (?:partner|investor) interests?)", ["partner interest transfer", "transfer split calculation"]);
  action("member_change", "open|apply|process|record|implement", "(?:member (?:change(?: record)?|admission|departure)|joiner treatment|leaver treatment|member commitment true up)", ["member admission", "member departure"]);
  action("investor_onboarding", "create|open|set up|update", "(?:investor (?:profiles?|records?|master|accounts?)|onboarding (?:record|case))", ["investor onboarding"]);
  action("investor_onboarding", "create|set up", "(?:investor|investor commitment) in (?:an? |the )?(?:crm|accounting system)");
  action("vesting", "calculate|allocate|reallocate|apply|compute|determine", "(?:(?:earned|vested|unvested|member) )?(?:carry points?|carry vesting|vesting (?:schedule|percentages?)|points and reallocation)", ["carry point reallocation", "carry vesting calculation"]);
  action("carry_recalculation", "calculate|recalculate|test", "(?:life to date |current period )?(?:carry|carried interest)(?: (?:income|allocation))?", ["carry income test", "carried interest recalculation"]);
  action("carry_recalculation", "perform|run", "(?:carry income test|carried interest income test)");
  action("clawback", "perform|run|calculate|test|assess|model", "(?:carry |carried interest )?clawback(?: test)?", ["clawback test", "clawback calculation"]);
  action("holdback", "calculate|retain|release|apply|record", "(?:carry )?holdbacks?", ["holdback calculation", "holdback release"]);
  action("wind_down", "wind down|liquidate|dissolve", "(?:carry )?(?:vehicle|fund|partnership)", ["vehicle wind down", "carry vehicle wind down"]);
  action("wind_down", "validate|verify|confirm", "zero (?:partner capital|member balances)");
  action("dual_ledger", "calculate|build|recalculate|allocate", "(?:capital interest (?:ledger|allocation)|carry interest (?:ledger|allocation)|capital and carry ledgers?)", ["two ledger allocation", "dual ledger allocation"]);
  action("investor_allocation", "run|execute|calculate|apply|recalculate|prepare|compute|determine", "(?:(?:investor|partner|capital|member) allocations?(?: rules?)?|allocation calculations?|taxable income allocations?)", ["investor allocation calculation", "capital allocation"]);
  action("investor_allocation", "allocate", "(?:capital|distributions?|proceeds|event amounts?) (?:among|between|to) (?:the )?(?:investors|partners|members)");
  action("investment_setup", "open|create|set up|establish", "(?:investment purchase|(?:issuer|security|investment|lot) (?:master|record|setup)|(?:issuer and security|security and issuer) master(?: data)?)", ["security master setup", "investment setup"]);
  action("investment_setup", "create|update", "[a-z][a-z0-9]* issuer and security master data");
  action("oid_amortization", "calculate|build|maintain|prepare|record", "(?:oid(?: warrant)? (?:amortization|accretion)|(?:original issue|loan) discount (?:amortization|accretion)|warrant (?:cost )?amortization)", ["oid amortization", "original issue discount amortization"]);
  action("oid_amortization", "amortize|accrete", "(?:oid|(?:original issue|loan) discount|(?:allocated )?warrant costs?)");
  action("warrant_valuation", "allocate|record|capture|calculate", "(?:warrant (?:costs?|allocations?|valuation)|(?:cost|proceeds) to (?:the )?warrants?)", ["warrant cost allocation"]);
  action("warrant_valuation", "record|capture", "warrant valuation allocated cost");
  action("asset_valuation", "value", "(?:shares|securities|assets|lots|in kind distribution)", ["security valuation", "asset valuation", "distribution valuation"]);
  action("asset_valuation", "set|calculate|determine|compute", "(?:(?:share|distribution|asset|security) valuation|(?:fair market|per share) value|price per share|value of (?:the )?(?:distribution|shares|securities))");
  action("security_conversion", "convert|restructure", "(?:safe|convertible notes?|notes? into (?:shares|equity)|securities into (?:shares|equity))", ["note conversion", "safe conversion", "non cash security conversion"]);
  action("security_conversion", "process|record|execute", "(?:safe(?:,? note,? or non cash)? conversion|(?:note|security|non cash) conversion)(?: where applicable)?");
  action("pik_accrual", "calculate|accrue|capitalize|capitalise|compute|record", "(?:pik(?: interest)?|payment in kind interest)", ["pik accrual", "pik interest calculation", "payment in kind interest accrual"]);
  action("cash_interest", "calculate|compute|accrue|recalculate", "(?:contractual )?cash (?:interest|coupon)", ["cash interest calculation"]);
  action("yield_calculation", "calculate|compute|model|recalculate", "(?:(?:effective|investment|contractual|loan|net|cash) )?(?:yield|internal rate of return|irr)", ["yield calculation", "effective yield calculation"]);
  action("loan_schedule", "create|build|prepare|model|update", "(?:loan (?:workbook|schedule|amortization schedule)|contractual schedule|debt service schedule|principal repayment schedule)", ["loan schedule preparation"]);
  action("expense_transfer", "record|post|enter|prepare|transfer", "(?:dtm (?:data|entries|amounts?)|due to manager (?:entries|expenses|amounts?)|(?:manager paid|management company) expenses (?:to|in) (?:the )?fund)", ["due to manager expense transfer"]);
  action("revenue_recognition", "recognize|recognise|defer|accrue", "(?:(?:fee|earned|monitoring fee|deferred) )?revenue", ["revenue recognition"]);
  action("revenue_recognition", "post", "invoices and recogni[sz]e revenue");
  action("fee_calculation", "calculate|compute|recalculate", "(?:(?:gross|net|management|monitoring|administration|catch up|advisory) )?fees?(?: catch up| offsets?)?", ["management fee calculation", "fee offset calculation"]);
  action("fee_calculation", "apply", "(?:fee offsets?|management fee offsets?|offsets,? waivers,? and carryforwards)");
  action("expense_allocation", "allocate|apportion|distribute", "(?:(?:fund|shared|vendor|operating|management company) )?(?:expenses?|costs?|charges?)", ["expense allocation"]);
  action("expense_allocation", "calculate|prepare|determine", "expense allocations?");
  action("expense_scrub", "scrub|review|validate", "(?:expense (?:coding|lines?|classifications?|receipts?)|personal expense classification|receipts and personal expense classification|travel and entertainment expenses?)", ["expense scrubbing", "expense line review"]);
  action("expense_scrub", "net", "(?:eligible )?refund (?:and )?charge pairs?");
  action("billing_exclusion", "exclude|segregate|separate|remove|flag", "(?:non ?billable (?:expenses?|lines?|items?|charges?)|['\"]?do not bill['\"]? (?:items?|lines?|charges?))", ["billing exclusion", "nonbillable expense exclusion"]);
  action("accrual", "book|calculate|record|post|compute|recognize|recognise", "(?:(?:expense|period|quarter end|audit|tax|fee offset|monitoring fee offset) )?accruals?", ["expense accrual", "accrual calculation"]);
  action("accrual", "accrue", "(?:(?:estimated|unpaid) )?(?:fees?|expenses?|audit costs?|tax costs?)");
  action("financial_statement", "prepare|generate|compose|produce|update|build|draft", "(?:(?:word |draft )?(?:financial|cash flow|income) statements?|balance sheets?|(?:q[1-4] )?footnotes?|statement disclosures?)", ["financial statement preparation", "financial statement generation"]);
  action("ledger_post", "post", "(?:(?:gl|journal|adjusting|ledger|accounting|reversal|cash|cost) (?:entries|entry)|entries|entry|transactions? to (?:the )?(?:general )?ledger)", ["journal entry posting", "general ledger posting"]);
  action("receivable", "build|track|establish|age|monitor|update|manage", "(?:(?:expected|outstanding|past due|capital call) )?(?:receivables?|amounts due|past due amounts?|accounts receivable)", ["receivables aging", "accounts receivable tracking"]);
  action("invoice", "draft|prepare|create|issue|send|enter|record|register|log|post|produce|receive|generate", "(?:(?:vendor|customer|sales|accounts receivable|fund and affiliate accounts receivable|portfolio company accounts receivable|fee|billing) )?invoices?", ["invoice processing", "invoice creation"]);
  action("period_close", "close", "(?:(?:accounting|reporting|fiscal) )?(?:period|quarter|month|year|books)", ["quarterly close", "period close", "month end close"]);
  action("period_close", "complete|perform", "(?:month end|quarter end|monthly|quarterly|period|monthly or period) close");
  action("balance_rollforward", "roll forward|carry forward", "(?:(?:prior|previous|opening|closing|quarterly|allocation|period|loan) )*(?:balances?|workbooks?|models?|engine|schedules?|file|position)", ["balance roll forward", "workbook roll forward"]);
  action("balance_rollforward", "carry", "workbook into (?:the )?new period");
  action("variance_analysis", "analyze|analyse|investigate|explain|classify|resolve|quantify", "(?:(?:material|balance|receipt|cash|recorded|period|unexpected|expected versus received) )?(?:variances?|balance movements?|differences)", ["variance analysis", "analytical review of balances"]);
  action("variance_analysis", "perform", "analytical review of (?:balances|accruals|movements)");
  // A leading reconciliation verb denotes the comparison itself, not whatever is mentioned after it.
  action("reconciliation", "reconcile|tie out", "(?:[a-z0-9]+)", ["reconciliation", "account reconciliation", "cash reconciliation", "tie out"]);
  action("cash_application", "match|apply|allocate|link", "(?:(?:bank|investor|cash|customer|incoming|unidentified) )?(?:receipts?|cash receipts?|received funds|receipts? to (?:an? |the )?investor)", ["cash application", "receipt matching"]);
  action("cash_application", "apply", "(?:cash|payments?|bank credits?) (?:to|against) (?:a |an |the )?(?:invoice|receivable|investor|outstanding)");
  action("cash_application", "compare", "(?:each )?receipt to (?:the )?expected amount");
  action("cash_classification", "classify|categorize|categorise", "(?:(?:cash|bank|incoming) )?(?:proceeds|cash movements?|cash sources|cash uses|cash inflows|cash outflows)", ["cash classification", "proceeds classification"]);
  action("cash_classification", "update|prepare|compile", "(?:life to date |cash )?sources and uses");
  action("payment_entry", "prepare|build|enter|input|create|key|draft", "(?:(?:bank|wire|electronic|outgoing) )?(?:payments?|wire instructions?|payment instructions?)", ["payment entry", "payment preparation", "wire entry"]);
  action("wire_release", "release|execute|transmit|send|authorize and release", "(?:(?:bank|outgoing|vendor|electronic|approved|investor) )?(?:payments?|wires?|wire transfers?)", ["wire release", "payment release", "bank payment execution"]);
  action("callback", "perform|make|conduct|complete|place", "(?:(?:independent|bank|verification|payment|outbound) )?call ?backs?", ["callback verification", "bank callback", "perform callback"]);
  action("callback", "verify", "(?:instructions|(?:bank|wire|payment) (?:details|instructions)) (?:via|by|through) (?:an? |the )?(?:independent )?call ?back");
  action("settlement", "monitor|check|track|confirm|verify", "(?:bank |payment |wire |trade |final )?settlement", ["settlement tracking", "settlement confirmation"]);
  action("liquidity", "check|forecast|validate|confirm|assess|calculate|model|test|project", "(?:forward |point in time and forward |current |available )?(?:liquidity|cash availabilit[y]|cash available|funding and liquidity)", ["liquidity assessment", "liquidity forecast"]);
  action("facility_draw", "prepare|initiate|submit|execute|process", "(?:(?:facility|loc|line of credit|loan) )?draw(?:down| request)?", ["facility drawdown", "facility draw request"]);
  action("facility_draw", "draw|borrow", "(?:funds |cash )?(?:under|against|from|on) (?:a |an |the )?(?:credit facility|line of credit|loc|facility)");
  action("facility_repayment", "repay", "(?:(?:outstanding|facility|loan) )?(?:principal|loan|borrowing|facility|line of credit|loc)", ["facility repayment", "loan repayment"]);
  action("facility_repayment", "calculate|prepare|execute|process", "(?:(?:loc|facility|loan) repayments?|repayment principal)");
  action("borrowing_base", "calculate|compute|certify|recalculate", "borrowing base(?: components?| capacity| amount)?", ["borrowing base calculation", "borrowing base certification"]);
  action("bank_setup", "open|set up|activate|establish|update|amend", "bank accounts?", ["bank account setup"]);
  action("bank_mandate", "prepare|refresh|confirm|set up|establish|update|amend|verify|change", "(?:bank mandates?|signatory mandates?|bank signatories|mandate and signator(?:y|ies))", ["bank mandate update", "bank mandate administration"]);
  action("foreign_exchange", "arrange|execute|book", "(?:foreign exchange|fx|currency conversion)", ["foreign exchange execution", "currency conversion"]);
  action("foreign_exchange", "convert|exchange", "(?:currency|currencies|cash into (?:the )?(?:payment|base|local) currency)");
  action("remittance_support", "complete|prepare|provide", "(?:tax |withholding )?remittance support", ["tax remittance support"]);
  action("remittance_support", "track", "(?:amounts withheld for tax|withheld (?:amounts|tax) for remittance)");
  action("population_lock", "freeze|lock|validate|check", "(?:(?:event|investor|member|eligible|participant) )?population", ["population gate", "population check", "population freeze"]);
  action("population_lock", "complete|perform", "(?:(?:event|investor|member|same commitment and) )?population (?:gate|check)");
  action("population_lock", "verify|confirm|check|determine", "(?:(?:investor|participant|member) eligibility|eligibility of (?:the )?(?:members|investors|participants))");
  action("rule_lock", "lock|freeze", "(?:(?:fund specific|waterfall|allocation|governing|calculation|run|approved) )*(?:rules?|rule set|method(?:ology)?)", ["methodology lock", "rule freeze"]);
  action("independent_review", "perform|conduct|complete|undertake|run", "(?:(?:internal and client|independent and director|independent|internal|client|manager|controller|director|second|peer|completeness|quarterly completeness|final|regional|fund affiliate|portfolio company) )review", ["independent review", "internal review", "client review", "manager review", "second review", "peer review"]);
  action("independent_review", "review", "(?:completed workbook|final workpapers)");
  action("approval", "seek|request|obtain|secure|collect", "(?:(?:client admission|dual|client|manager|written|senior|internal|admission|investment committee|board) )*(?:approval|authorization|sign off|signature)", ["client approval", "request approval", "dual authorization"]);
  action("approval", "approve|authorize|authorise|sign off on", "(?:(?:bank|investor|event|client) )?(?:payments?|packages?|amounts?|entries|allocations?|notices?|invoices?|release|instructions?|distributions?|capital calls?)");
  action("ownership_trace", "identify|verify|trace|map|establish", "(?:ultimate )?(?:beneficial owners(?:hip)?|controlling persons|ownership chain)", ["beneficial ownership verification", "beneficial ownership tracing"]);
  action("sanctions_screen", "perform|conduct|run|complete|execute", "(?:sanctions|watchlist|pep|adverse media) screening", ["sanctions screening", "watchlist screening", "pep screening"]);
  action("sanctions_screen", "screen", "(?:investors|counterparties|beneficial owners|names) against (?:a |an |the )?(?:sanctions|watchlist|pep)");
  action("sanctions_screen", "review|check|investigate|resolve", "(?:pep status|adverse media|(?:potential )?sanctions matches)");
  action("kyc", "perform|conduct|run|complete|execute", "(?:(?:investor|counterparty|aml) )?(?:kyc(?: screening| clearance| checks?)?|identity checks?|aml screening|cdd checks?)", ["kyc screening", "identity verification"]);
  action("risk_rating", "assign|set|calculate|determine", "(?:(?:client|investor|case|aml) )?risk (?:rating|score|classification)", ["risk rating assignment"]);
  action("covenant_check", "test|check|verify|monitor|assess", "(?:(?:facility|financial|loan) )?covenants?|available borrowing,? covenants", ["covenant compliance check", "facility covenant test"]);
  action("duplicate_check", "check for|identify|detect|flag|investigate|screen for", "duplicate (?:payments?|invoices?|entries|records?|transactions?)", ["duplicate detection", "duplicate payment check", "duplicate invoice check"]);
  action("duplicate_check", "duplicate check", "(?:invoices?|payments?|entries|records?)");
  action("duplicate_check", "check", "whether (?:the |an? )?(?:payment|invoice|record|entry) is (?:an? )?duplicate");
  action("duplicate_check", "log", "and duplicate check (?:the |an? )?(?:payment|invoice|record|entry)");
  action("blackline", "review|generate|run|produce|compare", "(?:document )?blacklines?|(?:document|statement) versions", ["blackline review", "document version comparison"]);
  action("blackline", "compare", "(?:(?:prior|previous) (?:year|period|quarter) )?(?:statements?|documents?) (?:against|with|to|versions)");
  action("clean_copy", "clean|sanitize|sanitise|redact", "(?:external|client|distribution) cop(?:y|ies)", ["external copy cleanup", "external copy redaction"]);
  action("clean_copy", "remove|strip", "(?:internal (?:review )?(?:marks?|comments?|notes?)|reviewer annotations?)");
  action("clean_copy", "remove|strip", "review marks from (?:the |an? )?(?:client|external) copy");
  action("clean_copy", "run", "(?:file cleanup macro|workbook cleanup macro)");
  action("exception", "resolve|escalate|investigate|handle|clear|log|close|track", "(?:(?:bank|regulatory|identified|open|report level|unresolved|payment|reconciliation) )?(?:exceptions?|discrepancies|queries|breaches|shortfalls)", ["exception handling", "exception escalation"]);
  action("audit_evidence", "file|archive|retain|collect|preserve|assemble", "(?:(?:review|supporting|transaction|audit|binder|case|close check and review|quarterly|posting) )?(?:evidence|support|records?|documentation|proof)", ["evidence filing", "audit evidence retention"]);
  action("access_control", "provision|test|grant|restrict|revoke|update|establish|remove|set up", "(?:(?:portal|user|investor|recipient|system) )?access", ["access provisioning", "portal access testing"]);
  action("access_control", "provision", "(?:authorized |approved |investor )?contacts");
  action("workbook_control", "run|rerun|validate|perform|execute", "(?:check of checks|workbook (?:controls?|checks?)|(?:horizontal|vertical|cross foot) checks?)", ["workbook checks", "check of checks"]);
  action("event_setup", "open|start|initiate", "(?:(?:capital|distribution|billing|investment|onboarding|kyc|transfer|close|payment) )?(?:event|cycle|case)", ["event intake", "event initiation"]);
  action("calendar", "establish|set up|build|prepare|update|create", "(?:(?:event|execution|restriction|timing and restriction) )?calendar", ["event scheduling"]);
  action("document_pack", "assemble|gather|collect|prepare|compile|receive", "(?:(?:event data|source|bank documentation|event|deal document|document|supporting document|documentation|securities law|certificate|supporting|standard|onboarding) )?(?:pack|package|documents|documentation|materials)", ["document assembly", "document collection"]);
  action("document_pack", "prepare", "and obtain clearance for (?:the |an? )?(?:securities law|regulatory|legal) package");
  action("workbook", "prepare|create|build|update|set up|populate|link", "(?:(?:quarterly|new quarter|statement|allocation|current period|prior period|full year cumulative|financial) )?workbooks?", ["workbook preparation", "workbook setup"]);
  action("notice", "prepare|draft|generate|send|issue|deliver|quality check|review", "(?:(?:investor|event|distribution|capital call) )?notices?", ["notice generation", "investor notice preparation"]);
  action("portal_release", "publish", "(?:(?:investor|reviewed|event|reporting) )?(?:notices?|packages?|reports?|campaigns?)", ["notice publication", "portal publication"]);
  action("portal_release", "release|launch", "(?:(?:email|investor|notice|portal|notification) )?campaign");
  action("handoff", "hand off|hand over|accept|receive|complete", "(?:(?:post event|treasury|process|event|work|downstream|upstream) )?handoffs?", ["handoff", "treasury handoff", "downstream handoff"]);
  action("handoff", "hand off|hand over|hand", "(?:to |(?:[a-z]+ ){0,3}to )(?:the )?[a-z]+");
  action("data_migration", "migrate|transfer", "(?:(?:client|accounting|investor|legacy|source) )?(?:data|records)(?= (?:from|into|to) )", ["data migration", "system migration"]);
  action("data_mapping", "map|crosswalk|remap", "(?:(?:source|target|coa|general ledger|account|investor|reference|system|data) )?(?:fields?|codes?|accounts?|columns?|transcodes|data)", ["field mapping", "chart of accounts mapping"]);
  action("data_mapping", "transform", "(?:source )?data using (?:the |an? )?(?:[a-z]+ ){0,3}mapping");
  action("data_import", "import|load|reimport|re import", "(?:into [a-z]+|(?:target|source|transaction|upload|billing|expense|client|investor|account|bank) (?:data|records?|files?|balances?|batches)|trial balance|data|records?|files?|expenses|balances|batch)", ["data import", "file import"]);
  action("data_import", "upload", "(?:import files?|data files?|transaction records?)(?= (?:to|into) )");
  action("data_export", "export|extract|pull", "(?:(?:source|bank|fund|account|portfolio company|detailed|general|trial) )*(?:data|records?|balances?|detail|ledger|tb|trial balance|transactions?|reports?)", ["data extraction", "data export", "trial balance export"]);
  action("audit_request", "log|track|manage|close|archive|update|establish", "(?:(?:audit|auditor|pbc|controlled) )?(?:requests? (?:cycle|list|log)|audit requests?|auditor requests?|pbc requests?)", ["audit request tracking"]);
  action("reminder", "send|issue|deliver", "(?:(?:privacy controlled|investor|payment|follow up|outstanding) )?reminders?", ["payment reminder delivery"]);

  // Fallback instruments describe a visible action, with no claim about an underlying
  // transaction. Recording a prior approval can be record maintenance, never new authorization.
  const specialistCount = rules.length;
  action("scope_setup", "define|determine|set|confirm|establish|identify", "(?:(?:engagement|event|case|migration|reporting|statement|work|process|project) )?scope", ["scope definition"]);
  action("scope_setup", "assign|name|identify", "(?:responsibility|responsibilities|(?:case |process |event )?owners?|responsible (?:person|party|people|role)|reviewers?)");
  action("route_work", "route|reroute|direct|assign|refer", "(?:(?:payment|regional|exception|approval|event|service|facility|onboarding) )?(?:events?|cases?|requests?|items?|packages?|work|exceptions?|payments?|approvals?)", ["case routing", "process routing"]);
  action("route_work", "select|determine|identify|validate|confirm", "(?:(?:regional|funding|payment|approval|event|account|payment and account) )?(?:path|route)");
  action("status_monitor", "check|review|confirm|track|assess|monitor|report|communicate|obtain", "(?:(?:event|payment|cash|funding|settlement|access|clearance|compliance|application|screening|delivery|account|receivable|kyc|risk|cutoff) )?status|(?:candidate receipts|bank activity|notice access|open items|pending items|milestones)", ["status tracking", "milestone tracking"]);
  action("status_monitor", "monitor|track", "(?:actual cash|payments?|follow ups|progress|completion|changes?|exceptions?)");
  action("rule_confirmation", "confirm|check|identify|interpret|review|validate|verify", "(?:(?:applicable|fund specific|governing|approved|allocation|carry|accounting|calculation|close specific|waterfall|special profits) )*(?:terms?|rules?|methods?|methodology|authority|legal basis|treatment choice|polic(?:y|ies))", ["governing terms review", "method confirmation"]);
  action("source_validation", "validate|verify|check|review|confirm", "(?:(?:required|source|executed|supporting|identity|approved|current|entity|input|expense|source data) )*(?:documentation|documents?|document set|source data|source inputs?|completeness|internal consistency|receipts|invoices?|mandates?)", ["source validation", "document completeness check"]);
  action("source_validation", "check|verify|validate|confirm", "(?:submitted |signed )?(?:tax forms?|w [89](?: w [89])?)(?: type| forms?| signatures?| completeness| details?)?");
  action("source_validation", "match|compare", "(?:every |each )?(?:(?:source|recorded|reported|prior|previous|historical|current|approved|opening|closing|target|actual|expected|investor|tracker|notice|bank|fund|final|access|payment) )*(?:receipts?|amounts?|support|records?|data|documents?|figures?|fields?|population|totals?|versions?|values?|balances?|status records?|cash|schedules?)(?: and (?:totals?|balances?|records?))?(?= (?:against|to|with) )");
  action("close_record", "close|archive", "(?:(?:audit|event|onboarding|transfer|receivable|case|request|payment|billing) )?(?:case|record|file|event|cycle|tracker|checklist|package)", ["case closure", "event closeout"]);
  action("record_update", "record|document|log|capture|enter|note|list|update|retain", "(?:[a-z0-9]+)", ["record maintenance", "register update"]);

  function normalize(value) {
    return typeof value === "string" ? value.slice(0, 600).normalize("NFKC").toLowerCase()
      .replace(/[‘’ʼ]/g, "'").replace(/[“”]/g, '"').replace(/[\-‐‑‒–—_\/]/g, " ").replace(/&/g, " and ")
      .replace(/\s+/g, " ").trim() : "";
  }
  const genericTitle = /^(?:(?:untitled|unnamed|process|workflow|perform|execute|complete) )?(?:task|step|activity|operation)(?: \d+)?$/;
  // A report, log, checklist, proposed action or instruction about a payment is not a payment.
  // This also blocks rules that name a subject but not its direct object in a compound noun.
  const continuation = /^(?:$|\s*[,.;:(]|\s+(?:and|or|for|from|to|under|on|against|by|with|at|after|before|through|via|using|across|among|in|into|per|between|when|as|that|of|which|until|if|without|during|based|once|according|where|separately|correctly)\b)/;
  const notAction = /\b(?:do not|does not|did not|should not|will not|must not|never|not required|not performed|not allowed|not approved|not applicable|instead of|rather than|not yet|not to|no longer|cannot|can't|no need|hypothetical|illustrative|simulation|simulate|simulated|test only|dry run|mock|sample|example only|proposed|proposal|planned|planning)\b/;
  function matchPhrase(raw) {
    const value = raw.replace(/[.!;:]+$/, "").trim();
    if (!value || value.includes("?") || notAction.test(value.replace(/["']do not bill["']/g, "nonbillable"))) return null;
    if (exact.has(value)) return byId.get(exact.get(value));
    // Only distribute a shared object to known coordinated verbs. Never search the middle of
    // a sentence: "review the policy on how to release wires" is not an instruction to release.
    const primary = value.replace(/^(?:independently |internally )/, "");
    // A bank transaction log is a record of work, not the channel that executes it.
    if (/^(?:create|enter|input|record|log|update)(?: or update)? (?:the |a )?(?:wire|payment|transaction|journal entry) (?:in|into|on) (?:the |a )?(?:(?:payments?|wire|event|transaction|internal) )?(?:log|tracker|register|checklist)\b/.test(primary)) return byId.get("record_update");
    const candidates = [primary];
    const shared = /^([a-z]+)(?:,\s*([a-z]+))?,?\s+(?:and|or)\s+(?:independently |internally |quality )?([a-z]+)\s+(.+)$/.exec(primary);
    const coordinated = word => verbs.has(word) || ["control", "save", "inventory", "reconcile", "split", "clean"].includes(word);
    if (shared && coordinated(shared[1]) && coordinated(shared[3]) && (!shared[2] || coordinated(shared[2]))) {
      for (const verb of [shared[1], shared[2], shared[3]].filter(Boolean)) candidates.push(verb + " " + shared[4]);
    }
    const phrases = [...new Set(candidates)];
    for (const [begin, end] of [[0, specialistCount], [specialistCount, rules.length]]) {
      for (const candidate of phrases) for (let i = begin; i < end; i++) {
        const {id, match} = rules[i];
        const result = match.exec(candidate);
        if (!result) continue;
        if (id === "wire_release" && /\b(?:for (?:client |manager |bank |internal )?(?:review|approval|verification)|to (?:the |a )?(?:reviewer|approver|approval queue|review queue)|for (?:a |an )?(?:test|dry run))\b/.test(candidate)) continue;
        const broadVerb = id === "reconciliation" || id === "record_update";
        if (broadVerb && /^(?:whether|if|how|to|why|what|for|that|then|before|after|in|into|out|off|on|up|with|review|retention|price|holders|breaker)$/.test(result[0].split(" ").at(-1))) continue;
        if (id==="reconciliation" && /^reconcile with .+ on\b/.test(candidate))continue;
        if (id==="record_update" && /^\s+(?:review|retention|price|holders|breaker)\b/.test(candidate.slice(result[0].length)))continue;
        if (id==="record_update" && /\b(?:in|into|on) (?:the |a )?(?:register|tracker|log|checklist|ledger)\b/.test(candidate))return byId.get(id);
        if (id==="record_update" && /^\s+(?:status|details?|amount|transactions?|entry|entries|adjustments?|dates?|changes?|balances?|records?|log|tracker|register|number|approval|decision|outcome|results?|notes?)\b/.test(candidate.slice(result[0].length)))return byId.get(id);
        if (id==="reconciliation" || continuation.test(candidate.slice(result[0].length))) return byId.get(id);
      }
    }
    return null;
  }
  function supportsInstrument(step) {
    return !!step && typeof step === "object" && (!step.type || ["activity", "subprocess", "document", "data_store"].includes(step.type));
  }
  function resolve(step) {
    if (!supportsInstrument(step)) return null;
    const title = normalize(step.title);
    if (title && !genericTitle.test(title)) return matchPhrase(title);
    // Descriptions may mention another team's work. Use only the first direct instruction,
    // or a sentence whose subject is explicitly the captured actor or "this step".
    const text = normalize(step.description).split(/[.;\n]/, 1)[0];
    const actor = normalize(step.actor);
    const subjects = ["this step ", ...(actor ? [actor + " ", "the " + actor + " "] : [])];
    const subject = subjects.find(prefix => text.startsWith(prefix));
    const predicate = subject ? text.slice(subject.length).replace(/^[a-z]+/, word => verbs.get(word) || word) : text;
    return matchPhrase(predicate);
  }
  function forDisplay(step, designId) {
    return supportsInstrument(step) && byId.has(designId) ? byId.get(designId) : resolve(step);
  }
  scope.CollectorComponents = Object.freeze({all, resolve, forDisplay});
})(window);
