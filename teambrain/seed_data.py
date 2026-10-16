"""Synthetic company data: Northwind Pay, a fictional Mumbai fintech.

Every person, project, meeting and decision here is made up for the demo.
"""

TEAMS = [
    {"id": "team-leadership", "name": "Leadership"},
    {"id": "team-payments", "name": "Payments"},
    {"id": "team-risk", "name": "Risk"},
    {"id": "team-platform", "name": "Platform"},
]

PEOPLE = [
    {"id": "p-dev", "name": "Dev Malhotra", "role": "CTO", "team": "team-leadership"},
    {"id": "p-asha", "name": "Asha Rao", "role": "Engineering Manager", "team": "team-payments"},
    {"id": "p-vikram", "name": "Vikram Iyer", "role": "Backend Engineer", "team": "team-payments"},
    {"id": "p-neha", "name": "Neha Kapoor", "role": "Product Manager", "team": "team-payments"},
    {"id": "p-rohan", "name": "Rohan Mehta", "role": "Risk Analytics Lead", "team": "team-risk"},
    {"id": "p-priya", "name": "Priya Nair", "role": "ML Engineer", "team": "team-risk"},
    {"id": "p-kabir", "name": "Kabir Shah", "role": "Compliance Officer", "team": "team-risk"},
    {"id": "p-meera", "name": "Meera Joshi", "role": "Platform Lead", "team": "team-platform"},
    {"id": "p-arjun", "name": "Arjun Das", "role": "Site Reliability Engineer", "team": "team-platform"},
    {"id": "p-sana", "name": "Sana Qureshi", "role": "Data Engineer", "team": "team-platform"},
]

PROJECTS = [
    {
        "id": "proj-autopay", "name": "UPI Autopay", "status": "in_progress",
        "summary": "Recurring UPI mandates for subscription merchants.",
        "team": "team-payments", "lead": "p-neha", "members": ["p-asha", "p-vikram", "p-kabir"],
    },
    {
        "id": "proj-fraud", "name": "Fraud Scoring v2", "status": "in_progress",
        "summary": "Real-time ML fraud score on every transaction.",
        "team": "team-risk", "lead": "p-priya", "members": ["p-rohan", "p-sana"],
    },
    {
        "id": "proj-ledger", "name": "Ledger Migration", "status": "in_progress",
        "summary": "Move the core ledger from the legacy monolith to a new double-entry service.",
        "team": "team-platform", "lead": "p-meera", "members": ["p-arjun", "p-sana", "p-vikram"],
    },
    {
        "id": "proj-onboarding", "name": "Merchant Onboarding Revamp", "status": "planned",
        "summary": "Cut merchant KYC-to-live time from 5 days to 1.",
        "team": "team-payments", "lead": "p-vikram", "members": ["p-neha", "p-kabir"],
    },
]

MEETINGS = [
    {
        "id": "m-1", "title": "UPI Autopay kickoff", "date": "2026-08-04", "project": "proj-autopay",
        "attendees": ["p-neha", "p-asha", "p-vikram", "p-kabir"],
        "notes": "Scoped v1 to subscription merchants. Debated aggregator vs direct NPCI integration.",
    },
    {
        "id": "m-2", "title": "Fraud model review", "date": "2026-08-20", "project": "proj-fraud",
        "attendees": ["p-priya", "p-rohan", "p-dev"],
        "notes": "Reviewed v2 model precision/recall. Agreed an auto-block threshold for launch.",
    },
    {
        "id": "m-3", "title": "Ledger cutover planning", "date": "2026-09-02", "project": "proj-ledger",
        "attendees": ["p-meera", "p-arjun", "p-sana", "p-vikram"],
        "notes": "Planned migration strategy. Main risk is balance drift between old and new ledgers.",
    },
    {
        "id": "m-4", "title": "Autopay compliance check", "date": "2026-09-10", "project": "proj-autopay",
        "attendees": ["p-kabir", "p-neha", "p-asha"],
        "notes": "Compliance reviewed e-mandate limits and re-authentication rules.",
    },
    {
        "id": "m-5", "title": "Fraud threshold retro", "date": "2026-09-25", "project": "proj-fraud",
        "attendees": ["p-priya", "p-rohan", "p-kabir", "p-asha"],
        "notes": "September chargebacks showed fraud slipping under the 0.85 threshold. Agreed to lower it.",
    },
    {
        "id": "m-6", "title": "Ledger go/no-go", "date": "2026-10-06", "project": "proj-ledger",
        "attendees": ["p-meera", "p-dev", "p-arjun", "p-asha"],
        "notes": "Dual-write showed zero drift for 10 days. Approved cutover date.",
    },
]

DECISIONS = [
    {
        "id": "d-1", "title": "Integrate NPCI mandate API directly, not via an aggregator",
        "rationale": "Lower latency and no per-transaction aggregator fee at our volume.",
        "date": "2026-08-04", "meeting": "m-1", "project": "proj-autopay", "by": "p-neha",
        "status": "active", "supersedes": None,
    },
    {
        "id": "d-2", "title": "Cap autopay debits at Rs 15,000 without re-authentication",
        "rationale": "Keeps v1 within e-mandate limits; higher amounts need customer re-auth.",
        "date": "2026-09-10", "meeting": "m-4", "project": "proj-autopay", "by": "p-kabir",
        "status": "active", "supersedes": None,
    },
    {
        "id": "d-3", "title": "Auto-block transactions with fraud score >= 0.85",
        "rationale": "Conservative launch threshold to limit false positives on good customers.",
        "date": "2026-08-20", "meeting": "m-2", "project": "proj-fraud", "by": "p-priya",
        "status": "superseded", "supersedes": None,
    },
    {
        "id": "d-4", "title": "Lower auto-block threshold to fraud score >= 0.78",
        "rationale": "September chargebacks showed too much fraud scoring 0.78-0.85; "
                     "false-positive cost judged lower than chargeback losses.",
        "date": "2026-09-25", "meeting": "m-5", "project": "proj-fraud", "by": "p-rohan",
        "status": "active", "supersedes": "d-3",
    },
    {
        "id": "d-5", "title": "Dual-write to old and new ledger for two weeks before cutover",
        "rationale": "Detect balance drift safely before switching reads.",
        "date": "2026-09-02", "meeting": "m-3", "project": "proj-ledger", "by": "p-meera",
        "status": "active", "supersedes": None,
    },
    {
        "id": "d-6", "title": "Cut over to the new ledger on 2026-10-20 with a 48h rollback window",
        "rationale": "Zero drift in dual-write; 48h window covers a full settlement cycle.",
        "date": "2026-10-06", "meeting": "m-6", "project": "proj-ledger", "by": "p-dev",
        "status": "active", "supersedes": None,
    },
]

DOCUMENTS = [
    {
        "id": "doc-1", "title": "UPI Autopay PRD", "kind": "PRD",
        "url": "https://wiki.northwindpay.example/autopay/prd",
        "summary": "Requirements for recurring UPI mandates: user flows, limits, failure handling.",
        "author": "p-neha", "project": "proj-autopay", "references": ["d-1"],
    },
    {
        "id": "doc-2", "title": "Autopay compliance memo", "kind": "Memo",
        "url": "https://wiki.northwindpay.example/autopay/compliance",
        "summary": "E-mandate limits, re-auth rules, and audit logging requirements for autopay.",
        "author": "p-kabir", "project": "proj-autopay", "references": ["d-2"],
    },
    {
        "id": "doc-3", "title": "Fraud Scoring v2 model card", "kind": "Model card",
        "url": "https://wiki.northwindpay.example/risk/fraud-v2",
        "summary": "Features, training data, evaluation metrics and threshold history for fraud v2.",
        "author": "p-priya", "project": "proj-fraud", "references": ["d-3", "d-4"],
    },
    {
        "id": "doc-4", "title": "Ledger migration runbook", "kind": "Runbook",
        "url": "https://wiki.northwindpay.example/platform/ledger-runbook",
        "summary": "Step-by-step cutover, drift checks, and rollback procedure.",
        "author": "p-arjun", "project": "proj-ledger", "references": ["d-5", "d-6"],
    },
    {
        "id": "doc-5", "title": "Merchant onboarding funnel analysis", "kind": "Analysis",
        "url": "https://wiki.northwindpay.example/payments/onboarding-funnel",
        "summary": "Where merchants drop off between signup and first live transaction.",
        "author": "p-sana", "project": "proj-onboarding", "references": [],
    },
]

# Used by the UI's "Load sample" button to demo ingest.
SAMPLE_NOTES = """Autopay limit review - 14 Oct 2026
Attendees: Kabir Shah, Neha Kapoor, Asha Rao, Dev Malhotra, Ishaan Verma (new Product Designer on the Payments team)

Insurance and mutual-fund merchants keep hitting the Rs 15,000 cap and customers are dropping off at re-authentication.
Kabir confirmed the higher limit is allowed for these merchant categories if we add an extra authentication factor at mandate setup.

Decision (Dev): raise the autopay cap to Rs 1,00,000 for insurance and mutual-fund merchants, with an extra authentication factor at mandate creation. This replaces the old Rs 15,000 cap for those categories.
Decision (Neha): Ishaan will redesign the mandate setup screen to include the extra factor.
"""
