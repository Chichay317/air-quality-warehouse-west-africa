import numpy as np

from pipeline.common import connect, get_all

COUNTRY = "NG"
BBOX = "2.67,4.27,14.68,13.89"     
CITIES = {"Lagos": (6.52, 3.38), "Abuja": (9.07, 7.49), "Ibadan": (7.38, 3.94), "Abeokuta": (7.16, 3.35),
          "Kano": (12.00, 8.52), "Kaduna": (10.52, 7.44), "Port Harcourt": (4.82, 7.03), "Benin City": (6.34, 5.63),
          "Enugu": (6.45, 7.51), "Jos": (9.90, 8.86), "Ilorin": (8.50, 4.55), "Maiduguri": (11.85, 13.16),
          "Calabar": (4.95, 8.32)}


def km_between(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return float(6371 * 2 * np.arcsin(np.sqrt(a)))


def nearest_city(lat, lon, max_km=60):
    name, km = min(((c, km_between(lat, lon, *xy)) for c, xy in CITIES.items()), key=lambda t: t[1])
    return name if km <= max_km else "Other"


LOCATION_SQL = """
INSERT INTO dim_location AS d (location_id, name, city, country, provider, latitude, longitude, is_reference)
VALUES (%(location_id)s, %(name)s, %(city)s, %(country)s, %(provider)s, %(latitude)s, %(longitude)s, %(is_reference)s)
ON CONFLICT (location_id) DO UPDATE SET
    name = EXCLUDED.name, city = EXCLUDED.city, country = EXCLUDED.country, provider = EXCLUDED.provider,
    latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, is_reference = EXCLUDED.is_reference, updated_at = now()
WHERE (d.name, d.city, d.country, d.provider, d.latitude, d.longitude, d.is_reference)
      IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.city, EXCLUDED.country, EXCLUDED.provider,
                        EXCLUDED.latitude, EXCLUDED.longitude, EXCLUDED.is_reference)
RETURNING (xmax = 0) AS inserted
"""

SENSOR_SQL = """
INSERT INTO dim_sensor AS d (sensor_id, location_id, parameter, units)
VALUES (%(sensor_id)s, %(location_id)s, %(parameter)s, %(units)s)
ON CONFLICT (sensor_id) DO UPDATE SET
    location_id = EXCLUDED.location_id, parameter = EXCLUDED.parameter, units = EXCLUDED.units, updated_at = now()
WHERE (d.location_id, d.parameter, d.units) IS DISTINCT FROM (EXCLUDED.location_id, EXCLUDED.parameter, EXCLUDED.units)
RETURNING (xmax = 0) AS inserted
"""


def upsert(conn, sql, rows):
    counts = {"new": 0, "changed": 0, "unchanged": 0}
    for row in rows:
        result = conn.execute(sql, row).fetchone()
        counts["unchanged" if result is None else "new" if result[0] else "changed"] += 1
    return counts


def main():
    locations = get_all("/v3/locations", bbox=BBOX)
    keep = [l for l in locations if l["country"]["code"] == COUNTRY and not l.get("isMobile")]
    print(f"OpenAQ returned {len(locations)} locations in the box; keeping {len(keep)} fixed locations in {COUNTRY}")

    location_rows, sensor_rows = [], []
    for l in keep:
        lat, lon = l["coordinates"]["latitude"], l["coordinates"]["longitude"]
        location_rows.append({"location_id": l["id"], "name": l.get("name") or f"location {l['id']}",
                              "city": nearest_city(lat, lon), "country": COUNTRY,
                              "provider": (l.get("provider") or {}).get("name") or "unknown",
                              "latitude": lat, "longitude": lon, "is_reference": bool(l.get("isMonitor"))})
        for s in l["sensors"]:
            sensor_rows.append({"sensor_id": s["id"], "location_id": l["id"],
                                "parameter": s["parameter"]["name"], "units": s["parameter"]["units"]})

    with connect() as conn:               
        loc = upsert(conn, LOCATION_SQL, location_rows)
        sen = upsert(conn, SENSOR_SQL, sensor_rows)
        totals = conn.execute("SELECT (SELECT count(*) FROM dim_location), (SELECT count(*) FROM dim_sensor)").fetchone()

    print(f"Locations: {loc['new']} new, {loc['changed']} changed, {loc['unchanged']} unchanged")
    print(f"Sensors:   {sen['new']} new, {sen['changed']} changed, {sen['unchanged']} unchanged")
    print(f"Now in the warehouse: {totals[0]} locations, {totals[1]} sensors")


if __name__ == "__main__":
    main()