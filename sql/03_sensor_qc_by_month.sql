TRUNCATE sensor_qc;
ALTER TABLE sensor_qc ADD COLUMN month DATE NOT NULL;
ALTER TABLE sensor_qc DROP CONSTRAINT sensor_qc_pkey;
ALTER TABLE sensor_qc ADD PRIMARY KEY (sensor_id, run_id, month);