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
    prerelease_version varchar(25),
    updated TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Abritrary version values at the (approx) time this was written; this don't really matter as
-- they'll get updated within a first few seconds of initial startup.
INSERT INTO release_versions (project, version, prerelease_version, updated) VALUES ('oxen-io/session-desktop', 'v1.7.3', NULL, '2021-10-14Z');
INSERT INTO release_versions (project, version, prerelease_version, updated) VALUES ('oxen-io/session-android', '1.11.11', NULL, '2021-10-14Z');
INSERT INTO release_versions (project, version, prerelease_version, updated) VALUES ('oxen-io/session-ios', '1.11.17', NULL, '2021-10-14Z');

CREATE TABLE release_notes (
    project varchar(50) NOT NULL,
    version varchar(25) NOT NULL,
    name TEXT,
    notes TEXT
);

CREATE INDEX release_notes_project_version ON release_notes(project, version);

CREATE TABLE release_assets (
    project varchar(50) NOT NULL,
    version varchar(25) NOT NULL,
    name varchar(225) NOT NULL,
    url varchar(225) NOT NULL
);

CREATE INDEX release_assets_project_version ON release_assets(project, version);

INSERT INTO release_assets (project, version, name, url) VALUES ('oxen-io/session-desktop', 'v1.7.3', 'Test name', 'github.com');

CREATE TABLE account_version_checks (
    blinded_id varchar(66) NOT NULL,
    platform varchar(25) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_blinded_id_platform_timestamp UNIQUE (blinded_id, platform, timestamp)
);

CREATE INDEX account_version_checks_blinded_id ON account_version_checks(blinded_id);

CREATE TABLE session_token_stats (
    current_value NUMERIC(20, 6) NOT NULL,
    total_nodes INT NOT NULL,
    total_tokens_staked INT NOT NULL,
    circulating_supply INT NOT NULL,
    total_supply INT NOT NULL,
    staking_reward_pool INT NOT NULL,
    updated TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Abritrary values at the (approx) time this was written; this don't really matter as
-- they'll get updated within a first few seconds of initial startup.
INSERT INTO session_token_stats (current_value, total_nodes, total_tokens_staked, circulating_supply, total_supply, staking_reward_pool, updated) VALUES (0.099002, 2194, 30400000, 68297852, 68297852, 40000000, '2024-06-14Z');

COMMIT;

-- vim:ft=sql
