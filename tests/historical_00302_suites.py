"""Reviewed Node inventory of the sealed 003-02 receipt (2026-11-15).

Historical receipts cover the suites available at capture time. The current
004-05 recorder discovers all current suites independently. Neither inventory
pins implementation bytes or changes the historical outcome.
"""
NODE = (
    'bidding_v1_checks.cjs', 'browser_observer_checks.cjs',
    'bulk_background_checks.cjs', 'bulk_transfer_checks.cjs',
    'durability_page_checks.cjs', 'durability_worker_checks.cjs',
    'e2e_live_v2_page_checks.cjs', 'e2e_page_checks.cjs',
    'final_inactive_checks.cjs', 'final_owned_checks.cjs',
    'list_refresh_checks.cjs', 'market_discovery_bridge_checks.cjs',
    'market_discovery_followup_v1_checks.cjs', 'native_status_checks.cjs',
    'occupancy_native_checks.cjs', 'pricing_timing_checks.cjs',
    'production_bulk_checks.cjs', 'production_diagnostics_checks.cjs',
    'production_inventory_checks.cjs', 'production_metadata_checks.cjs',
    'production_page_checks.cjs', 'production_worker_checks.cjs',
    'read_bridge_checks.cjs', 'resale_native_checks.cjs',
    'search_validation_v1_checks.cjs', 'transaction_bridge_checks.cjs',
    'watched_bulk_v1_checks.cjs',
)
