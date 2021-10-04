-- add anti_phish to config

ALTER TABLE config
    ADD COLUMN anti_phish boolean NOT NULL DEFAULT false;
