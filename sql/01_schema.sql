CREATE TABLE dim_location (
    location_id   INTEGER PRIMARY KEY,            
    name          TEXT NOT NULL,
    city          TEXT NOT NULL,             
    country       CHAR(2) NOT NULL,
    provider      TEXT NOT NULL,
    latitude      DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude     DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    is_reference  BOOLEAN NOT NULL,              
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dim_sensor (
    sensor_id     INTEGER PRIMARY KEY,          
    location_id   INTEGER NOT NULL REFERENCES dim_location,
    parameter     TEXT NOT NULL,                      
    units         TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pipeline_run (                         
    run_id        SERIAL PRIMARY KEY,
    job           TEXT NOT NULL,                
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed'))
);

CREATE TABLE load_log (          
    run_id          INTEGER NOT NULL REFERENCES pipeline_run,
    sensor_id       INTEGER NOT NULL REFERENCES dim_sensor,
    window_from     TIMESTAMPTZ NOT NULL,
    window_to       TIMESTAMPTZ NOT NULL,
    rows_fetched    INTEGER NOT NULL,
    rows_duplicate  INTEGER NOT NULL,             
    rows_new        INTEGER NOT NULL,
    rows_changed    INTEGER NOT NULL,        
    rows_unchanged  INTEGER NOT NULL,
    finished_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, sensor_id),
    CHECK (rows_duplicate + rows_new + rows_changed + rows_unchanged = rows_fetched)  
);

CREATE TABLE stg_hourly (                
    sensor_id      INTEGER NOT NULL REFERENCES dim_sensor,
    hour_utc       TIMESTAMPTZ NOT NULL,           
    value          DOUBLE PRECISION,           
    observed_count INTEGER,                    
    expected_count INTEGER,
    run_id         INTEGER NOT NULL REFERENCES pipeline_run,
    PRIMARY KEY (sensor_id, hour_utc)                 
);

CREATE TABLE fact_hourly (           
    sensor_id      INTEGER NOT NULL REFERENCES dim_sensor,
    hour_utc       TIMESTAMPTZ NOT NULL,
    value          DOUBLE PRECISION NOT NULL,
    observed_count INTEGER,
    expected_count INTEGER,
    run_id         INTEGER NOT NULL REFERENCES pipeline_run,
    PRIMARY KEY (sensor_id, hour_utc)
);

CREATE TABLE qc_quarantine (            
    sensor_id      INTEGER NOT NULL REFERENCES dim_sensor,
    hour_utc       TIMESTAMPTZ NOT NULL,
    value          DOUBLE PRECISION,
    rule           TEXT NOT NULL,                     
    detail         TEXT,
    run_id         INTEGER NOT NULL REFERENCES pipeline_run,
    PRIMARY KEY (sensor_id, hour_utc, rule)
);

CREATE TABLE sensor_qc (             
    sensor_id      INTEGER NOT NULL REFERENCES dim_sensor,
    run_id         INTEGER NOT NULL REFERENCES pipeline_run,
    status         TEXT NOT NULL CHECK (status IN ('ok', 'quarantined', 'unchecked')),
    rule           TEXT,
    detail         TEXT,
    PRIMARY KEY (sensor_id, run_id)
);

CREATE INDEX ON stg_hourly (hour_utc);
CREATE INDEX ON fact_hourly (hour_utc);
CREATE INDEX ON dim_sensor (location_id);