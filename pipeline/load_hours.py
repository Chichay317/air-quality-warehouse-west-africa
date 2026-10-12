import argparse
from datetime import datetime, timedelta, timezone

from pipeline.common import PAGE, connect, get

PARAMETERS = ["pm25", "relativehumidity"]
HISTORY_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
OVERLAP = timedelta(hours=48)
CHUNK = timedelta(days=40)               

UPSERT_SQL = """
WITH upserted AS (
    INSERT INTO stg_hourly AS s (sensor_id, hour_utc, value, observed_count, expected_count, run_id)
    SELECT DISTINCT ON (sensor_id, hour_utc) sensor_id, hour_utc, value, observed_count, expected_count, %(run_id)s
    FROM incoming ORDER BY sensor_id, hour_utc
    ON CONFLICT (sensor_id, hour_utc) DO UPDATE SET
        value = EXCLUDED.value, observed_count = EXCLUDED.observed_count,
        expected_count = EXCLUDED.expected_count, run_id = EXCLUDED.run_id
    WHERE (s.value, s.observed_count, s.expected_count)
          IS DISTINCT FROM (EXCLUDED.value, EXCLUDED.observed_count, EXCLUDED.expected_count)
    RETURNING (xmax = 0) AS inserted
)
SELECT count(*) FILTER (WHERE inserted), count(*) FILTER (WHERE NOT inserted) FROM upserted
"""


def sensor_span(sensor_id):
    s = get(f"/v3/sensors/{sensor_id}")["results"][0]
    first, last = s.get("datetimeFirst"), s.get("datetimeLast")
    if not first or not last:
        return None
    parse = lambda d: datetime.fromisoformat(d["utc"].replace("Z", "+00:00"))
    return parse(first), parse(last)


def fetch_hours(sensor_id, start, end):
    rows, piece_start = [], start
    while piece_start < end:
        piece_end = min(piece_start + CHUNK, end)
        page = 1
        while True:
            batch = get(f"/v3/sensors/{sensor_id}/hours", datetime_from=piece_start.isoformat(),
                        datetime_to=piece_end.isoformat(), limit=PAGE, page=page)["results"]
            for h in batch:
                hour = datetime.fromisoformat(h["period"]["datetimeFrom"]["utc"].replace("Z", "+00:00"))
                if piece_start <= hour < piece_end:
                    cov = h.get("coverage") or {}
                    rows.append((sensor_id, hour, h.get("value"), cov.get("observedCount"), cov.get("expectedCount")))
            if len(batch) < PAGE:
                break
            page += 1
        piece_start = piece_end
    return rows


def load_sensor(conn, run_id, sensor_id, start, end, rows):
    with conn.transaction():
        conn.execute("TRUNCATE incoming")
        with conn.cursor().copy("COPY incoming FROM STDIN") as copy:     
            for row in rows:
                copy.write_row(row)
        distinct = conn.execute("SELECT count(DISTINCT hour_utc) FROM incoming").fetchone()[0]
        new, changed = conn.execute(UPSERT_SQL, {"run_id": run_id}).fetchone()
        counts = {"fetched": len(rows), "duplicate": len(rows) - distinct, "new": new,
                  "changed": changed, "unchanged": distinct - new - changed}
        conn.execute("""INSERT INTO load_log (run_id, sensor_id, window_from, window_to, rows_fetched,
                        rows_duplicate, rows_new, rows_changed, rows_unchanged)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (run_id, sensor_id, start, end, *counts.values()))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-sensors", type=int, help="load only this many sensors (for a quick test)")
    args = parser.parse_args()
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)  

    conn = connect()
    conn.autocommit = True                    
    run_id = conn.execute("INSERT INTO pipeline_run (job) VALUES ('load_hours') RETURNING run_id").fetchone()[0]
    sensors = conn.execute("""
        SELECT s.sensor_id, s.parameter, max(h.hour_utc) AS last_hour
        FROM dim_sensor s LEFT JOIN stg_hourly h USING (sensor_id)
        WHERE s.parameter = ANY(%s)
        GROUP BY s.sensor_id, s.parameter ORDER BY s.sensor_id""", (PARAMETERS,)).fetchall()[:args.max_sensors]
    conn.execute("""CREATE TEMP TABLE incoming (sensor_id INTEGER, hour_utc TIMESTAMPTZ, value DOUBLE PRECISION,
                    observed_count INTEGER, expected_count INTEGER)""")
    print(f"Run {run_id}: {len(sensors)} sensors, loading up to {end:%Y-%m-%d %H:00} UTC")

    totals = dict.fromkeys(["fetched", "duplicate", "new", "changed", "unchanged"], 0)
    failed, status = [], "failed"
    try:
        for i, (sensor_id, parameter, last_hour) in enumerate(sensors, 1):
            start = HISTORY_START if last_hour is None else max(HISTORY_START, last_hour + timedelta(hours=1) - OVERLAP)
            try:                                 
                try:
                    span = sensor_span(sensor_id)  
                except Exception as e:
                    print(f"  sensor {sensor_id}: active period unavailable ({e}); trying the whole window")
                    span = (start, end)
                rows = []
                if span is not None:
                    fetch_from = max(start, span[0].replace(minute=0, second=0, microsecond=0))
                    fetch_to = min(end, span[1] + timedelta(hours=1))
                    if fetch_from < fetch_to:
                        rows = fetch_hours(sensor_id, fetch_from, fetch_to)
                counts = load_sensor(conn, run_id, sensor_id, start, end, rows)
            except Exception as e:
                failed.append(sensor_id)
                print(f"[{i}/{len(sensors)}] sensor {sensor_id} ({parameter}) FAILED: {e}")
                continue
            totals = {k: totals[k] + counts[k] for k in totals}
            print(f"[{i}/{len(sensors)}] sensor {sensor_id} ({parameter}) from {start:%Y-%m-%d %H:00}: "
                  f"{counts['fetched']} fetched, {counts['new']} new, {counts['changed']} changed, "
                  f"{counts['unchanged']} unchanged, {counts['duplicate']} duplicate")
        status = "succeeded" if not failed else "failed"
    finally:                                  
        conn.execute("UPDATE pipeline_run SET status = %s, finished_at = now() WHERE run_id = %s", (status, run_id))
        conn.close()
        print(f"\nRun {run_id} {status}. Totals: " + ", ".join(f"{v} {k}" for k, v in totals.items()))
        if failed:
            print(f"{len(failed)} sensor(s) failed and will be retried on the next run: {failed}")


if __name__ == "__main__":
    main()