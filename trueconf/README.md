# TrueConf Server

Video conferencing server, run from TrueConf's official image
(`trueconf/trueconf-server:stable`). Free edition: register at
https://trueconf.com (search "TrueConf Server Free") to get a registration
key by email, or skip that and activate later through the web control
panel — either way the server runs unlicensed/trial until activated.

## Why this stack looks different from the others

Every other stack in this repo is a `docker-compose.yml` deployed via
`scripts/deploy.sh`, which runs `docker compose up -d --build` on every
push. **TrueConf's own docs explicitly warn against that**: recreating the
container via Compose `up`/`down` invalidates the server's license. So this
stack is deliberately plain `docker run`, managed with the scripts below,
and is **not** touched by `scripts/deploy.sh`.

| Rule | Why |
| --- | --- |
| Never run `run.sh` twice for the same container name | It refuses on purpose — re-running `docker run` would create a second, unlicensed container. |
| Use `start.sh`/`stop.sh` for routine restarts | `docker start`/`stop` reuse the same container; the license survives. |
| Only use `remove.sh` when you intend to rebuild from scratch | Removing the container may require re-registering the license. |
| Don't add this to any `docker-compose.yml` | Confirmed by TrueConf's docs to risk license invalidation on `up`/`down`. |

## Files

- `flags.env` — non-secret: image tag, ports, data directory paths, and
  optional `TRUECONF_SERVER_ID`/`TRUECONF_SERVER_NAME` for license
  activation at launch.
- `.env.example` / `.env` — secrets: admin login, admin password, and the
  registration `Serial`. `.env` is gitignored; generate it with
  `./gen-env.sh` (random admin password) or copy and edit
  `.env.example` by hand if you already have a `Serial`.
- `run.sh` — one-time launch. Refuses to run if a container with the
  configured name already exists.
- `start.sh` / `stop.sh` — routine lifecycle, safe to run repeatedly.
- `remove.sh` — deletes the container (asks for confirmation first); data
  under `TRUECONF_DATA_DIR` is untouched.

## Start (local or VM — same either way, this isn't part of deploy.sh)

```sh
cd trueconf
./gen-env.sh        # writes .env with a generated ADMIN_PASSWORD
./run.sh
```

Then open `http://<host>:80` and either finish activation through the
control panel, or set `TRUECONF_SERIAL` in `.env` and
`TRUECONF_SERVER_ID`/`TRUECONF_SERVER_NAME` in `flags.env` before `run.sh`
to activate at launch.

To add another admin (only works once `TRUECONF_DATA_DIR` is mounted, which
it always is here):

```sh
sudo apt install -yq apache2-utils
htpasswd -c -d -b passwd new_admin password
cat passwd >> data/lib/docker/passwd
echo new_admin >> data/lib/docker/tcadmins   # or tcsecadmins for security-admin only
```

## Ports

| Port | Purpose |
| --- | --- |
| `80` | HTTP / web control panel |
| `443` | HTTPS |
| `4307` | TrueConf protocol |
| `53000-55000/udp` | WebRTC media (optional but included by default) |

## Data

`TRUECONF_DATA_DIR` (default `./data/lib`) holds all server state —
back it up like you would any database. `TRUECONF_LOG_DIR` and
`TRUECONF_WEBMANAGER_DIR` (SSL certs, HTTPS config, IP restrictions) are
separate mounts so logs can be rotated/pruned independently. TLS certs must
be `.crt`/`.key` named `tls.crt`/`tls.key` under the webmanager dir.

## Updating

Check the [TrueConf changelog](https://trueconf.com/products/changelog.html#server)
for your version jump — some ranges need a `pg_dumpall` export/restore
before relaunching with `INIT_DB=true`, others just need pull + relaunch
with the same mounts. Don't automate this blindly; read the notes for the
specific versions involved first, then: `stop.sh`, `remove.sh`,
`docker pull trueconf/trueconf-server:<new-tag>`, update `TRUECONF_IMAGE`
in `flags.env`, `run.sh` again with the same `TRUECONF_DATA_DIR`.
