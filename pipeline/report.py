import os
import sys
from datetime import datetime, timezone

from pipeline.common import connect

CHECKS = {
    "Every fetched row is accounted for (duplicate + new + changed + unchanged = fetched)":
        """SELECT count(*) = 0 FROM load_log
           WHERE rows_duplicate + rows_new + rows_changed + rows_unchanged <> rows_fetched""",
    "Staging holds exactly the rows the loader reported as new":
        "SELECT (SELECT count(*) FROM stg_hourly) = (SELECT coalesce(sum(rows_new), 0) FROM load_log)",
    "Every staged hour is either clean or quarantined, never both, never neither":
        """SELECT (SELECT count(*) FROM fact_hourly) + (SELECT count(DISTINCT (sensor_id, hour_utc)) FROM qc_quarantine)
                  = (SELECT count(*) FROM stg_hourly)
              AND NOT EXISTS (SELECT 1 FROM fact_hourly f JOIN qc_quarantine q USING (sensor_id, hour_utc))""",
    "Clean and quarantined hours all come from the latest quality check":
        """SELECT NOT EXISTS (SELECT 1 FROM fact_hourly WHERE run_id <> (SELECT max(run_id) FROM pipeline_run
                                                                   WHERE job = 'quality_check' AND status = 'succeeded'))
              AND NOT EXISTS (SELECT 1 FROM qc_quarantine WHERE run_id <> (SELECT max(run_id) FROM pipeline_run
                                                                   WHERE job = 'quality_check' AND status = 'succeeded'))""",
    "No run is stuck in 'running'":
        "SELECT count(*) = 0 FROM pipeline_run WHERE status = 'running'",
}

SUMMARIES = {
    "Data in the warehouse": """
        SELECT s.parameter, count(DISTINCT h.sensor_id) AS sensors, count(*) AS staged_hours,
               min(h.hour_utc)::date AS first, max(h.hour_utc)::date AS last
        FROM stg_hourly h JOIN dim_sensor s USING (sensor_id) GROUP BY 1 ORDER BY 1""",
    "Hours caught by each rule": """
        SELECT rule, count(*) AS hours, count(DISTINCT sensor_id) AS sensors
        FROM qc_quarantine GROUP BY 1 ORDER BY 1""",
    "Sensor-month verdicts (latest quality check)": """
        SELECT status, count(*) AS sensor_months FROM sensor_qc
        WHERE run_id = (SELECT max(run_id) FROM sensor_qc) GROUP BY 1 ORDER BY 1""",
    "Pipeline runs": """
        SELECT job, status, count(*) AS runs FROM pipeline_run GROUP BY 1, 2 ORDER BY 1, 2""",
    "Daily PM2.5 by city (clean data, median across sensors; WHO 24-hour guideline is 15 µg/m³)": """
        SELECT city, count(*) AS days, round(avg(sensors), 1) AS avg_sensors_per_day,
               round(avg(pm25_median), 1) AS avg_pm25, round(100.0 * avg((pm25_median > 15)::int)) AS pct_days_above_who
        FROM daily_city_pm25 GROUP BY city ORDER BY days DESC""",
}


def markdown_table(cur):
    names = [c.name for c in cur.description]
    rows = cur.fetchall()
    lines = ["| " + " | ".join(names) + " |", "|" + "---|" * len(names)]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def main():
    with connect() as conn:
        results = {name: conn.execute(sql).fetchone()[0] for name, sql in CHECKS.items()}
        tables = {title: markdown_table(conn.execute(sql)) for title, sql in SUMMARIES.items()}

    lines = [f"# Warehouse report", f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "", "## Reconciliation checks", ""]
    lines += [f"- {'PASS' if ok else 'FAIL'}: {name}" for name, ok in results.items()]
    for title, table in tables.items():
        lines += ["", f"## {title}", "", table]
    text = "\n".join(lines) + "\n"

    os.makedirs("results", exist_ok=True)
    with open("results/warehouse_report.md", "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print("Saved results/warehouse_report.md")
    if not all(results.values()):
        sys.exit("At least one reconciliation check failed.")


if __name__ == "__main__":
    main()