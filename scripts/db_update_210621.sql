-- add "logging_config" column to config table

ALTER TABLE config
    ADD COLUMN logging_config json;

UPDATE config SET logging_config = '{}';

ALTER TABLE config
    ALTER COLUMN logging_config SET NOT NULL;