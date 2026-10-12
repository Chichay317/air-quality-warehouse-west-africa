# Warehouse report
Generated 2026-10-12 22:46 UTC

## Reconciliation checks

- PASS: Every fetched row is accounted for (duplicate + new + changed + unchanged = fetched)
- PASS: Staging holds exactly the rows the loader reported as new
- PASS: Every staged hour is either clean or quarantined, never both, never neither
- PASS: Clean and quarantined hours all come from the latest quality check
- PASS: No run is stuck in 'running'

## Data in the warehouse

| parameter | sensors | staged_hours | first | last |
|---|---|---|---|---|
| pm25 | 101 | 277160 | 2024-01-01 | 2026-10-12 |
| relativehumidity | 72 | 184099 | 2025-02-11 | 2026-10-12 |

## Hours caught by each rule

| rule | hours | sensors |
|---|---|---|
| H1_missing_value | 435 | 13 |
| H2_below_valid_range | 14889 | 25 |
| H3_above_valid_range | 1 | 1 |
| H4_isolated_spike | 659 | 51 |
| H5_stuck_value | 7142 | 2 |
| H8_known_misplaced_location | 4908 | 2 |
| S1_disagrees_with_neighbours | 13137 | 15 |
| S2_mostly_zero | 14868 | 1 |

## Sensor-month verdicts (latest quality check)

| status | sensor_months |
|---|---|
| ok | 497 |
| quarantined | 67 |
| unchecked | 151 |

## Pipeline runs

| job | status | runs |
|---|---|---|
| load_hours | failed | 5 |
| load_hours | succeeded | 2 |
| quality_check | succeeded | 3 |

## Daily PM2.5 by city (clean data, median across sensors; WHO 24-hour guideline is 15 µg/m³)

| city | days | avg_sensors_per_day | avg_pm25 | pct_days_above_who |
|---|---|---|---|---|
| Lagos | 724 | 8.9 | 23.8 | 71 |
| Abuja | 692 | 1.3 | 41.0 | 92 |
| Calabar | 572 | 1.0 | 26.0 | 71 |
| Ibadan | 141 | 4.3 | 29.1 | 97 |
| Enugu | 71 | 1.0 | 14.2 | 45 |
| Port Harcourt | 61 | 2.2 | 21.7 | 75 |
