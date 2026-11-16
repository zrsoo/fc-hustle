"""Required suite inventory of the sealed Objective 002-11 regression record.

These are historical command names, not source-byte assertions. New regression
runners discover the current tree; archived evidence is judged against its own
reviewed inventory, so adding a test cannot invalidate an older honest receipt.
"""
PYTHON = (
    'test_001d01_inventory.py',
    'test_001d02_contract.py',
    'test_001d03_native_prices.py',
    'test_001d04_pricing.py',
    'test_001d05_inventory.py',
    'test_001d06_foundation.py',
    'test_001d07_handoff.py',
    'test_00201_native_status.py',
    'test_00202_pricing_optimization.py',
    'test_00203_discovery.py',
    'test_00203_gate.py',
    'test_00203_preflight.py',
    'test_00204_actors.py',
    'test_00205_occupancy.py',
    'test_00206_capacity.py',
    'test_00207_enrollment.py',
    'test_00208_resale.py',
    'test_00209_bulk.py',
    'test_00210_relist.py',
    'test_00211_sold.py',
    'test_bidding_v1.py',
    'test_bulk_transfer_v1.py',
    'test_durability_v1.py',
    'test_integration_harness.py',
    'test_market_pricing.py',
    'test_production_diagnostics.py',
    'test_watched_bulk_v1.py',
)
NODE = (
    'bidding_v1_checks.cjs',
    'bulk_transfer_checks.cjs',
    'native_status_checks.cjs',
    'occupancy_native_checks.cjs',
    'pricing_timing_checks.cjs',
    'production_bulk_checks.cjs',
    'production_diagnostics_checks.cjs',
    'production_inventory_checks.cjs',
    'production_metadata_checks.cjs',
    'production_page_checks.cjs',
    'production_worker_checks.cjs',
    'resale_native_checks.cjs',
    'watched_bulk_v1_checks.cjs',
)
