-- add custom message option for kicks and bans

ALTER TABLE config
    ADD COLUMN custom_kick_message text;
ALTER TABLE config
    ADD COLUMN custom_ban_message text;

UPDATE config SET custom_kick_message = '';
UPDATE config SET custom_ban_message = '';

ALTER TABLE config
    ALTER COLUMN custom_kick_message SET NOT NULL;
ALTER TABLE config
    ALTER COLUMN custom_ban_message SET NOT NULL;
