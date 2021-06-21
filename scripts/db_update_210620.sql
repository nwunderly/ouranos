-- add "note" infraction type

ALTER TABLE history
    ADD COLUMN note integer[];

UPDATE history SET note = '{}';

ALTER TABLE history
    ALTER COLUMN note SET NOT NULL;