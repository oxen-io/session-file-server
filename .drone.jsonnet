local docker_base = 'registry.oxen.rocks/lokinet-ci-';
local apt_get_quiet = 'apt-get -o=Dpkg::Use-Pty=0 -q';

local default_deps = [
  'python3',
  'python3-pytest',
  'python3-coloredlogs',
  'python3-flask',
  'python3-pycryptodome',
  'python3-nacl',
  'python3-requests',
  'python3-session-util',
];

// Regular build on a debian-like system:
local debian_pipeline(name,
                      image,
                      arch='amd64',
                      deps=default_deps,
                      before_pytest=[],
                      pytest_opts='',
                      extra_cmds=[],
                      services=[],
                      allow_fail=false) = {
  kind: 'pipeline',
  type: 'docker',
  name: name,
  platform: { arch: arch },
  trigger: { branch: { exclude: ['debian/*', 'ubuntu/*'] } },
  steps: [
    {
      name: '🐍 pytest',
      image: image,
      pull: 'always',
      [if allow_fail then 'failure']: 'ignore',
      commands: [
                  'echo "Running on ${DRONE_STAGE_MACHINE}"',
                  'echo "man-db man-db/auto-update boolean false" | debconf-set-selections',
                  apt_get_quiet + ' update',
                  apt_get_quiet + ' install -y eatmydata',
                  'eatmydata ' + apt_get_quiet + ' install --no-install-recommends -y lsb-release',
                  'cp contrib/deb.oxen.io.gpg /etc/apt/trusted.gpg.d',
                  'echo deb http://deb.oxen.io $$(lsb_release -sc) main >/etc/apt/sources.list.d/oxen.list',
                  'eatmydata ' + apt_get_quiet + ' update',
                  'eatmydata ' + apt_get_quiet + ' dist-upgrade -y',
                  'eatmydata ' + apt_get_quiet + ' install --no-install-recommends -y ' + std.join(' ', deps),
                  'cp fileserver/config.py.sample fileserver/config.py',
                ] + before_pytest + [
                  'PYTHONPATH=. python3 -mpytest -vv --color=yes ' + pytest_opts,
                ]
                + extra_cmds,
    },
  ],
  services: services,
};

local debian_pg_pipeline(name, image, pg_tag='bullseye') = debian_pipeline(
  name,
  image,
  deps=default_deps + ['python3-pip', 'postgresql-client'],
  services=[
    { name: 'pg', image: 'postgres:bullseye', environment: { POSTGRES_USER: 'ci', POSTGRES_PASSWORD: 'ci' } },
  ],
  before_pytest=[
    'pip3 install psycopg psycopg-pool',
    'for i in $(seq 0 30); do if pg_isready -d ci -h pg -U ci -t 1; then break; fi; if [ "$i" = 30 ]; then echo "Timeout waiting for postgresql" >&2; exit 1; fi; sleep 1; done',
  ],
  pytest_opts='--pgsql "postgresql://ci:ci@pg/ci"'
);

[
  {
    name: 'Lint checks',
    kind: 'pipeline',
    type: 'docker',
    platform: { arch: 'amd64' },
    steps: [
      {
        name: 'Formatting',
        image: docker_base + 'debian-stable',
        commands: [
          'echo "Running on ${DRONE_STAGE_MACHINE}"',
          apt_get_quiet + ' install -y black',
          'black --check --diff --color .',
        ],
      },
      {
        name: 'Flake8',
        image: docker_base + 'debian-stable',
        commands: [
          'echo "Running on ${DRONE_STAGE_MACHINE}"',
          apt_get_quiet + ' install -y flake8',
          'flake8 .',
        ],
      },
    ],
  },

  debian_pg_pipeline('PostgreSQL 13/bullseye', docker_base + 'debian-stable', pg_tag='13-bullseye'),
]
