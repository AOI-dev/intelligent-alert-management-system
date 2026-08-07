# Zabbix stack

Self-contained Zabbix monitoring stack on MySQL: server, nginx frontend, database
and a bundled agent that monitors the host it runs on.

| Service         | Image                              | Exposed        |
| --------------- | ---------------------------------- | -------------- |
| `mysql`         | `mysql:8.0`                        | internal only  |
| `zabbix-server` | `zabbix/zabbix-server-mysql`       | `10051/tcp`    |
| `zabbix-web`    | `zabbix/zabbix-web-nginx-mysql`    | `8080/tcp`     |
| `zabbix-agent`  | `zabbix/zabbix-agent2`             | internal only  |

## Start

```sh
./scripts/gen-env.sh     # writes .env with random DB passwords
docker compose up -d
```

The frontend comes up on <http://localhost:8080>. First login is `Admin` /
`zabbix` — change it immediately, it is the stock Zabbix default and is not
something this repo can set for you.

Schema creation on first boot takes a minute or two; `zabbix-server` restarts
until MySQL has finished importing. Follow it with `docker compose logs -f
zabbix-server`.

## Configuration

Everything is driven by `.env` — see `.env.example` for the full list. The
values worth touching:

- `ZABBIX_VERSION` — image tag shared by server, web and agent. Keep them equal;
  a frontend newer than its server refuses to start.
- `PHP_TZ` — frontend timezone, e.g. `Europe/Kyiv`.
- `ZABBIX_WEB_PORT` / `ZABBIX_SERVER_PORT` — host bindings if 8080 or 10051 are
  taken.
- `ZBX_CACHESIZE`, `ZBX_STARTPOLLERS` — raise as the number of monitored hosts
  grows.

`.env` is gitignored. It does **not** travel with a `git push`, so the deploy
host needs its own copy next to `docker-compose.yml` before `docker compose up`
will start.

## First-boot fixup: the bundled agent's interface

Zabbix seeds a host named `Zabbix server` whose agent interface is hardcoded to
`127.0.0.1`. Inside the server container that address is the server itself, not
the agent, so every passive item fails with `another network error` until the
interface is repointed at the `zabbix-agent` service. Active checks work
regardless, which is why the agent looks half-alive rather than dead.

In the frontend: *Data collection → Hosts → Zabbix server → Interfaces*, switch
the agent interface from IP to DNS and set the name to `zabbix-agent`.

This lives in the database, not in this repo — redo it after any
`docker compose down -v`.

## Agent privileges

`zabbix-agent` runs `privileged: true` with `pid: host` so host-level metrics
(processes, kernel counters) are visible from inside the container. Drop both if
you only want the container's own view — the agent still starts, it just reports
on itself.

## Data

MySQL lives in the `mysql-data` named volume; `docker compose down` keeps it,
`docker compose down -v` destroys it along with all history. Back up with:

```sh
docker compose exec mysql mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" zabbix > zabbix-backup.sql
```
