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

-- Session Releases
CREATE TABLE projects (
    id BIGSERIAL PRIMARY KEY,
    name varchar(50) NOT NULL,
    updated timestamp with time zone NOT NULL DEFAULT NOW()
);

CREATE TABLE releases (
    id BIGSERIAL PRIMARY KEY,
    project BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    prerelease BOOLEAN NOT NULL DEFAULT FALSE,
    version_code BIGINT NOT NULL,
    url varchar(255) NOT NULL,
    name varchar(255),
    notes text,
    UNIQUE(project, version_code)
);

CREATE TABLE release_assets (
    release BIGINT NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    name varchar(255) NOT NULL,
    url varchar(255) NOT NULL
);
CREATE INDEX ON release_assets(release);

CREATE VIEW versions AS
    SELECT
        releases.id as id,
        projects.name as proj_name,
        version_code,
        version_code / 1000000 || '.' || version_code % 1000000 / 1000 || '.' || version_code % 1000 AS version,
        prerelease,
        url,
        releases.name AS name,
        notes
    FROM releases JOIN projects ON releases.project = projects.id;

CREATE VIEW release_versions AS SELECT * FROM versions WHERE NOT prerelease;
CREATE VIEW prerelease_versions AS SELECT * FROM versions WHERE prerelease;

-- Insert project information
INSERT INTO projects (name) VALUES ('oxen-io/session-desktop');
INSERT INTO projects (name) VALUES ('oxen-io/session-android');
INSERT INTO projects (name) VALUES ('oxen-io/session-ios');

-- Account Versioning
CREATE TABLE account_version_checks (
    blinded_id varchar(66) NOT NULL,
    platform varchar(25) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX account_version_checks_blinded_id ON account_version_checks(blinded_id);

-- Token Info
CREATE TABLE session_token_stats (
    maximum_supply INT NOT NULL,
    sent_per_node INT NOT NULL,
    staking_reward_pool INT NOT NULL
);
CREATE TABLE session_token_history (
    current_value NUMERIC(20, 6) NOT NULL,
    circulating_supply INT NOT NULL,
    total_nodes INT NOT NULL,
    updated TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);


COMMIT;

-- vim:ft=sql
