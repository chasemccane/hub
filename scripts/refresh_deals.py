#!/usr/bin/env python3
"""
Daily Salesforce refresh for deal-data.json
Updates: pbr, stage, close date, created date for each deal.
Run via GitHub Actions or manually: python scripts/refresh_deals.py
"""

import json
import os
import sys
from datetime import datetime, timezone

try:
    from simple_salesforce import Salesforce, SalesforceResourceNotFound
except ImportError:
    print("ERROR: Run 'pip install simple-salesforce' first.")
    sys.exit(1)

# ── Auth ──────────────────────────────────────────────────────────────────────
SF_USERNAME       = os.environ['SF_USERNAME']
SF_PASSWORD       = os.environ['SF_PASSWORD']
SF_SECURITY_TOKEN = os.environ['SF_SECURITY_TOKEN']
SF_DOMAIN         = os.getenv('SF_DOMAIN', '')       # set to 'test' for sandbox

auth_kwargs = dict(
    username=SF_USERNAME,
    password=SF_PASSWORD,
    security_token=SF_SECURITY_TOKEN,
)
if SF_DOMAIN:
    auth_kwargs['domain'] = SF_DOMAIN

print("Connecting to Salesforce…")
sf = Salesforce(**auth_kwargs)
print(f"Connected: {sf.sf_instance}")

# ── Load deal-data.json ───────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'deal-data.json')
with open(DATA_FILE) as f:
    data = json.load(f)

# ── Collect Opportunity IDs ───────────────────────────────────────────────────
sf_ids = []
id_to_deal = {}
for deal_id, deal in data['deals'].items():
    sf_info = deal.get('sf', {})
    opp_id = sf_info.get('id')
    if opp_id:
        sf_ids.append(opp_id)
        id_to_deal[opp_id] = deal_id

if not sf_ids:
    print("No Salesforce IDs found in deal-data.json — nothing to refresh.")
    sys.exit(0)

# ── Query Salesforce ──────────────────────────────────────────────────────────
ids_str = "', '".join(sf_ids)
soql = f"""
    SELECT Id, Name, StageName, CloseDate, Projected_Billed_Revenue__c, CreatedDate
    FROM Opportunity
    WHERE Id IN ('{ids_str}')
""".strip()

print(f"Querying {len(sf_ids)} opportunities…")
result = sf.query(soql)
records = result.get('records', [])
print(f"Got {len(records)} records.")

# Stage name passthrough — Shopify Salesforce stages match hub display names
STAGE_MAP = {
    'Pre-Qualified': 'Pre-Qualified',
    'Envision':      'Envision',
    'Solution':      'Solution',
    'Demonstrate':   'Demonstrate',
    'Closed Won':    'Closed Won',
    # Add any Salesforce-specific stage names that differ:
    # 'Proposal/Price Quote': 'Solution',
}

# ── Apply updates ─────────────────────────────────────────────────────────────
updated_count = 0
for rec in records:
    opp_id   = rec['Id']
    deal_id  = id_to_deal.get(opp_id)
    if not deal_id:
        continue

    sf_node = data['deals'][deal_id].setdefault('sf', {})
    sf_node['id'] = opp_id

    # PBR
    pbr = rec.get('Projected_Billed_Revenue__c')
    sf_node['pbr'] = int(pbr) if pbr is not None else 0

    # Stage
    stage_sf = rec.get('StageName', '')
    sf_node['stage'] = STAGE_MAP.get(stage_sf, stage_sf)

    # Close Date — Salesforce returns "YYYY-MM-DD"
    close = rec.get('CloseDate')
    if close:
        sf_node['close'] = close  # keep as ISO YYYY-MM-DD

    # Created Date — Salesforce returns ISO datetime, keep just the date
    created = rec.get('CreatedDate')
    if created:
        sf_node['created'] = created[:10]

    print(f"  {deal_id}: stage={sf_node['stage']}, close={sf_node.get('close')}, pbr={sf_node['pbr']}")
    updated_count += 1

# ── Update timestamp ──────────────────────────────────────────────────────────
data['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
data['version'] = 2

# ── Write back ────────────────────────────────────────────────────────────────
with open(DATA_FILE, 'w') as f:
    json.dump(data, f, indent=2)

print(f"\nDone. {updated_count} deals refreshed. Timestamp: {data['updated']}")
