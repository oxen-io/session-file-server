BEGIN;

CREATE TABLE files (
    id VARCHAR(44) PRIMARY KEY CHECK(id ~ '^[a-zA-Z0-9_-]+$'),
    data BYTEA NOT NULL,
    uploaded TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expiry TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW() + '30 days'
);

/* Disable default compression of data because we expect to always be given encrypted (and therefore
 * uncompressable) data: */
ALTER TABLE files ALTER COLUMN data SET STORAGE EXTERNAL;

CREATE INDEX files_expiry ON files(expiry);

CREATE TABLE release_versions (
    project varchar(50) PRIMARY KEY,
    version varchar(25) NOT NULL,
    updated TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Abritrary version values at the (approx) time this was written; this don't really matter as
-- they'll get updated within a first few seconds of initial startup.
INSERT INTO release_versions (project, version, updated) VALUES ('oxen-io/session-desktop', 'v1.7.3', '2021-10-14Z');
INSERT INTO release_versions (project, version, updated) VALUES ('oxen-io/session-android', '1.11.11', '2021-10-14Z');
INSERT INTO release_versions (project, version, updated) VALUES ('oxen-io/session-ios', '1.11.17', '2021-10-14Z');

COMMIT;

-- vim:ft=sql
