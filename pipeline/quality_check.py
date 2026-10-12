import numpy as np
import pandas as pd

from pipeline.common import connect

EXPECTED_UNITS = {"pm25": "µg/m³", "relativehumidity": "%"}
VALID_RANGE = {"pm25": (0, 1000), "relativehumidity": (0, 100)}    
SPIKE_FLOOR, SPIKE_FACTOR = 100, 5  
STUCK_HOURS = 12           
RATIO_LOW, RATIO_HIGH = 1 / 3, 3      
MIN_NEIGHBOURS, MIN_SHARED_HOURS = 3, 50  
ZERO_SHARE_MAX = 0.2        
KNOWN_MISPLACED = {          
    "AUPP Liger Leadership Academy": "a school in Phnom Penh, Cambodia; OpenAQ's coordinates put it in Yobe State",
}


def hour_rules(stg):
    bad = []
    def add(mask, rule, detail):
        hit = stg[mask]
        bad.append(pd.DataFrame({"sensor_id": hit.sensor_id, "hour_utc": hit.hour_utc, "rule": rule,
                                 "detail": [detail(r) for r in hit.itertuples()] if len(hit) else []}))

    add(stg.value.isna(), "H1_missing_value", lambda r: "no value")
    low = stg.parameter.map(lambda p: VALID_RANGE[p][0]); high = stg.parameter.map(lambda p: VALID_RANGE[p][1])
    too_low = np.where(stg.parameter == "pm25", stg.value <= low, stg.value < low)
    add(pd.Series(too_low, index=stg.index) & stg.value.notna(), "H2_below_valid_range", lambda r: f"value {r.value}")
    add(stg.value > high, "H3_above_valid_range", lambda r: f"value {r.value}")
    add(stg.units != stg.parameter.map(EXPECTED_UNITS), "H7_unexpected_units", lambda r: f"units {r.units}")
    add(stg.location_name.isin(KNOWN_MISPLACED), "H8_known_misplaced_location", lambda r: KNOWN_MISPLACED[r.location_name])

    for sensor_id, g in stg[stg.parameter == "pm25"].groupby("sensor_id"):
        v = g.set_index("hour_utc").value.sort_index().asfreq("h")      
        around = pd.concat([v.shift(2), v.shift(1), v.shift(-1), v.shift(-2)], axis=1).median(axis=1)
        spikes = v[(v > SPIKE_FLOOR) & (v > SPIKE_FACTOR * around)]
        bad.append(pd.DataFrame({"sensor_id": sensor_id, "hour_utc": spikes.index, "rule": "H4_isolated_spike",
                                 "detail": [f"{x:.0f} vs {m:.0f} around it" for x, m in zip(spikes, around[spikes.index])]}))
        runs = (v != v.shift()).cumsum()                               
        length = v.groupby(runs).transform("size")
        stuck = v[(length >= STUCK_HOURS) & v.notna()]
        bad.append(pd.DataFrame({"sensor_id": sensor_id, "hour_utc": stuck.index, "rule": "H5_stuck_value",
                                 "detail": [f"{x} repeated {n} hours" for x, n in zip(stuck, length[stuck.index])]}))
    return pd.concat(bad, ignore_index=True)


def sensor_rules(stg, hour_bad):
    pm = stg[stg.parameter == "pm25"].copy()
    pm["month"] = pm.hour_utc.dt.strftime("%Y-%m-01")
    zero_share = pm.value.eq(0).groupby([pm.sensor_id, pm.month]).mean()

    clean = pm.merge(hour_bad[["sensor_id", "hour_utc"]].drop_duplicates(), how="left", indicator=True)
    clean = clean[clean._merge == "left_only"]
    ratios = [pd.DataFrame(columns=["sensor_id", "month", "ratio"])]
    for city, g in clean.groupby("city"):
        if city == "Other":                               
            continue
        wide = g.pivot(index="hour_utc", columns="sensor_id", values="value")
        for sensor_id in wide.columns:
            others = wide.drop(columns=sensor_id)
            both = (others.notna().sum(axis=1) >= MIN_NEIGHBOURS) & wide[sensor_id].notna()
            r = wide.loc[both, sensor_id] / others[both].median(axis=1)
            ratios.append(pd.DataFrame({"sensor_id": sensor_id, "month": r.index.strftime("%Y-%m-01"), "ratio": r.values}))
    by_month = pd.concat(ratios).groupby(["sensor_id", "month"]).ratio.agg(["median", "size"])

    verdicts = []
    for (sensor_id, month), share in zero_share.items():
        med, n = by_month.loc[(sensor_id, month)] if (sensor_id, month) in by_month.index else (np.nan, 0)
        if share > ZERO_SHARE_MAX:
            verdicts.append((sensor_id, month, "quarantined", "S2_mostly_zero", f"{share:.0%} of hours read exactly 0"))
        elif n < MIN_SHARED_HOURS:
            verdicts.append((sensor_id, month, "unchecked", None, f"{int(n)} hours with {MIN_NEIGHBOURS}+ neighbours"))
        elif RATIO_LOW <= med <= RATIO_HIGH:
            verdicts.append((sensor_id, month, "ok", None, f"median ratio {med:.2f} over {int(n)} hours"))
        else:
            verdicts.append((sensor_id, month, "quarantined", "S1_disagrees_with_neighbours",
                             f"median ratio {med:.2f} over {int(n)} hours"))
    return pd.DataFrame(verdicts, columns=["sensor_id", "month", "status", "rule", "detail"])


def main():
    conn = connect()
    conn.autocommit = True
    run_id = conn.execute("INSERT INTO pipeline_run (job) VALUES ('quality_check') RETURNING run_id").fetchone()[0]
    status = "failed"
    try:
        cur = conn.execute("""SELECT h.sensor_id, h.hour_utc, h.value, h.observed_count, h.expected_count,
                                     s.parameter, s.units, l.city, l.provider, l.name AS location_name
                              FROM stg_hourly h JOIN dim_sensor s USING (sensor_id) JOIN dim_location l USING (location_id)""")
        stg = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
        stg["hour_utc"] = pd.to_datetime(stg.hour_utc, utc=True)
        print(f"Run {run_id}: checking {len(stg):,} staged hours from {stg.sensor_id.nunique()} sensors")

        hour_bad = hour_rules(stg)
        verdicts = sensor_rules(stg, hour_bad)
        bad_months = verdicts.loc[verdicts.status == "quarantined", ["sensor_id", "month", "rule"]]
        pm = stg.loc[stg.parameter == "pm25", ["sensor_id", "hour_utc"]].copy()
        pm["month"] = pm.hour_utc.dt.strftime("%Y-%m-01")
        month_bad = pm.merge(bad_months, on=["sensor_id", "month"]).drop(columns="month")
        month_bad["detail"] = "whole sensor-month quarantined"
        bad = pd.concat([hour_bad, month_bad], ignore_index=True)
        bad = bad.merge(stg[["sensor_id", "hour_utc", "value"]], on=["sensor_id", "hour_utc"])

        keys = bad[["sensor_id", "hour_utc"]].drop_duplicates()
        good = stg.merge(keys, how="left", indicator=True)
        good = good[good._merge == "left_only"]

        with conn.transaction():     
            conn.execute("TRUNCATE fact_hourly, qc_quarantine")
            with conn.cursor().copy("COPY fact_hourly (sensor_id, hour_utc, value, observed_count, expected_count, run_id) FROM STDIN") as cp:
                for r in good.itertuples():
                    cp.write_row((r.sensor_id, r.hour_utc, r.value, None if pd.isna(r.observed_count) else int(r.observed_count),
                                  None if pd.isna(r.expected_count) else int(r.expected_count), run_id))
            with conn.cursor().copy("COPY qc_quarantine (sensor_id, hour_utc, value, rule, detail, run_id) FROM STDIN") as cp:
                for r in bad.itertuples():
                    cp.write_row((r.sensor_id, r.hour_utc, None if pd.isna(r.value) else r.value, r.rule, r.detail, run_id))
            with conn.cursor().copy("COPY sensor_qc (sensor_id, run_id, month, status, rule, detail) FROM STDIN") as cp:
                for r in verdicts.itertuples():
                    cp.write_row((int(r.sensor_id), run_id, r.month, r.status, None if pd.isna(r.rule) else r.rule, r.detail))
            fact_n, quar_n = conn.execute("SELECT (SELECT count(*) FROM fact_hourly), "
                                          "(SELECT count(DISTINCT (sensor_id, hour_utc)) FROM qc_quarantine)").fetchone()
            if fact_n + quar_n != len(stg):    
                raise RuntimeError(f"reconciliation failed: {fact_n} + {quar_n} != {len(stg)}")
        status = "succeeded"
    finally:
        conn.execute("UPDATE pipeline_run SET status = %s, finished_at = now() WHERE run_id = %s", (status, run_id))
        conn.close()

    print("\nHours caught by each rule (an hour can break more than one):")
    print(bad.groupby("rule").size().to_string())
    print("\nPM2.5 sensor-months by verdict:")
    print(verdicts.status.value_counts().to_string())
    info = stg[["sensor_id", "provider", "city"]].drop_duplicates()
    q = verdicts[verdicts.status == "quarantined"].merge(info, on="sensor_id")
    print("\nSensors with quarantined months:")
    print(q.groupby(["provider", "city", "sensor_id", "rule"]).month.agg(months="size", first="min", last="max").to_string()
          if len(q) else "none")
    print(f"\nReconciliation: {len(stg):,} staged = {fact_n:,} clean + {quar_n:,} quarantined. Run {run_id} {status}.")


if __name__ == "__main__":
    main()