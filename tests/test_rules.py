import numpy as np
import pandas as pd

from pipeline.load_dimensions import nearest_city
from pipeline.quality_check import hour_rules, sensor_rules


def make_stg(values, sensor_id=1, parameter="pm25", units="µg/m³", city="Lagos",
             location_name="site", start="2026-07-01"):
    hours = pd.date_range(start, periods=len(values), freq="h", tz="UTC")
    return pd.DataFrame({"sensor_id": sensor_id, "hour_utc": hours, "value": values, "parameter": parameter,
                         "units": units, "city": city, "provider": "test", "location_name": location_name})


def rules_caught(stg):
    return set(hour_rules(stg).rule)


def steady(n=48, level=20.0):
    return list(level + np.sin(np.arange(n)) * 3)


# --- city assignment -------------------------------------------------------------

def test_point_in_lagos_is_lagos():
    assert nearest_city(6.45, 3.40) == "Lagos"

def test_point_far_from_every_city_is_other():
    assert nearest_city(6.07, 8.34) == "Other"         


# --- hour rules ------------------------------------------------------------------

def test_clean_data_passes_every_hour_rule():
    assert rules_caught(make_stg(steady())) == set()

def test_missing_value_is_caught():
    v = steady(); v[10] = np.nan
    assert "H1_missing_value" in rules_caught(make_stg(v))

def test_zero_pm25_is_caught_but_zero_humidity_is_allowed():
    v = steady(); v[5] = 0.0
    assert "H2_below_valid_range" in rules_caught(make_stg(v))
    h = [50.0] * 5 + [0.0] + [50.0 + i for i in range(10)]
    assert "H2_below_valid_range" not in rules_caught(make_stg(h, parameter="relativehumidity", units="%"))

def test_impossible_values_are_caught():
    v = steady(); v[7] = 1500.0
    assert "H3_above_valid_range" in rules_caught(make_stg(v))
    h = [60.0 + i for i in range(10)]; h[3] = 104.0
    assert "H3_above_valid_range" in rules_caught(make_stg(h, parameter="relativehumidity", units="%"))

def test_unexpected_units_are_caught():
    assert "H7_unexpected_units" in rules_caught(make_stg(steady(), units="ppm"))

def test_known_misplaced_location_is_caught():
    assert "H8_known_misplaced_location" in rules_caught(make_stg(steady(), location_name="AUPP Liger Leadership Academy"))

def test_isolated_spike_is_caught():
    v = steady(); v[20] = 400.0
    bad = hour_rules(make_stg(v))
    assert list(bad[bad.rule == "H4_isolated_spike"].hour_utc.dt.hour) == [20]

def test_smooth_real_event_is_not_a_spike():
    v = steady(); v[18:23] = [150.0, 372.0, 527.0, 231.0, 136.0]    
    assert "H4_isolated_spike" not in rules_caught(make_stg(v))

def test_twelve_identical_hours_are_stuck_but_eleven_are_not():
    v12 = steady(); v12[10:22] = [33.0] * 12
    v11 = steady(); v11[10:21] = [33.0] * 11
    assert (hour_rules(make_stg(v12)).rule == "H5_stuck_value").sum() == 12
    assert "H5_stuck_value" not in rules_caught(make_stg(v11))

def test_humidity_at_100_for_many_hours_is_not_stuck():
    h = [100.0] * 20 + [80.0 + i for i in range(10)]            
    assert "H5_stuck_value" not in rules_caught(make_stg(h, parameter="relativehumidity", units="%"))


# --- sensor rules ----------------------------------------------------------------

def city_of_sensors(n_sensors=5, days=62, broken=None, factor=0.1, broken_from_day=0, city="Lagos"):
    rng = np.random.default_rng(0)
    base = 20 + 5 * np.sin(np.arange(days * 24) / 24 * 2 * np.pi)
    frames = []
    for s in range(1, n_sensors + 1):
        v = base * rng.lognormal(0, 0.1, len(base))
        if s == broken:
            v[broken_from_day * 24:] *= factor
        frames.append(make_stg(np.round(v, 1), sensor_id=s, city=city))
    return pd.concat(frames, ignore_index=True)


def verdicts_for(stg, sensor_id):
    v = sensor_rules(stg, hour_rules(stg))
    return dict(zip(v[v.sensor_id == sensor_id].month, v[v.sensor_id == sensor_id].status))

def test_sensor_agreeing_with_neighbours_is_ok():
    assert set(verdicts_for(city_of_sensors(), 1).values()) == {"ok"}

def test_sensor_that_breaks_loses_only_its_bad_month():
    stg = city_of_sensors(broken=3, broken_from_day=31)              
    assert verdicts_for(stg, 3) == {"2026-07-01": "ok", "2026-08-01": "quarantined"}

def test_too_few_neighbours_means_unchecked_not_ok():
    stg = city_of_sensors(n_sensors=3, broken=2)                  
    assert set(verdicts_for(stg, 2).values()) == {"unchecked"}

def test_month_with_many_zeros_is_quarantined():
    v = steady(24 * 30); v[::3] = [0.0] * len(v[::3])              
    stg = make_stg(v, city="Other")
    assert set(verdicts_for(stg, 1).values()) == {"quarantined"}