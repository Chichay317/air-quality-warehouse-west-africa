CREATE OR REPLACE VIEW daily_pm25 AS
WITH h AS (
    SELECT f.sensor_id,
           (f.hour_utc AT TIME ZONE 'Africa/Lagos')::date AS day,
           extract(hour FROM f.hour_utc AT TIME ZONE 'Africa/Lagos')::int / 6 AS block,
           f.value
    FROM fact_hourly f JOIN dim_sensor s USING (sensor_id)
    WHERE s.parameter = 'pm25'
)
SELECT h.sensor_id, l.city, l.provider, h.day,
       round(avg(h.value)::numeric, 1) AS pm25_mean,
       count(*) AS hours
FROM h JOIN dim_sensor s USING (sensor_id) JOIN dim_location l USING (location_id)
GROUP BY h.sensor_id, l.city, l.provider, h.day
HAVING count(*) >= 18 AND count(DISTINCT h.block) = 4;

CREATE OR REPLACE VIEW daily_city_pm25 AS
SELECT city, day,
       count(*) AS sensors,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pm25_mean)::numeric, 1) AS pm25_median
FROM daily_pm25
WHERE city <> 'Other'
GROUP BY city, day;