# Active Directory (pilot stand-in)

A small Samba4 AD DC, standing in for the "AD as nominal reference" role in
АР-07 (`artifacts/requirements-traceability.md`). It is **not** wired into
`platform` yet — `platform/scripts/seed_synthetic_ad.py` still writes its
own synthetic org chart straight into TimescaleDB. This stack exists so a
real LDAP/Kerberos directory is available to test against later, without
committing to that integration now.

Image: [`nowsci/samba-domain`](https://hub.docker.com/r/nowsci/samba-domain)
— a maintained community Samba4 AD DC image, commonly used for exactly this
kind of dev/test directory (not Microsoft's own AD, but LDAP/Kerberos/DNS
wire-compatible with it).

## Start

```sh
./gen-env.sh     # writes secret-only .env with a random domain admin password
set -a; . .env; . flags.env; set +a
docker compose up -d
docker compose logs -f samba-ad-dc   # provisioning takes a minute or two
```

No host ports are published — the directory is reachable only from other
containers on the `active-directory_active-directory` network (АР-14). To
query it during setup/testing, exec into the container rather than exposing
ports to the host:

```sh
docker compose exec samba-ad-dc samba-tool user list
docker compose exec samba-ad-dc ldapsearch -x -H ldap://localhost \
  -b "dc=pilot,dc=internal" -D "administrator@PILOT.INTERNAL" -W
```

## Configuration

- `flags.env` — committed: `AD_DOMAIN` (realm), `AD_HOST_IP` (the
  container's static IP on the fixed-subnet `active-directory` network —
  Samba AD DC needs one for its own DNS zone), image version.
- `.env` — gitignored, secret-only: `AD_ADMIN_PASSWORD`. Generate with
  `./gen-env.sh`.
- `NOCOMPLEXITY=true` and `INSECURELDAP=true` are set for pilot convenience
  (plain LDAP, relaxed password policy) — this is synthetic test data only,
  never point it at a real corporate identity.

## Seeding synthetic accounts

Nothing seeds automatically. `scripts/create_synthetic_users.sh [count]`
creates `count` (default 8) test accounts cycling through the same
synthetic org chart `platform/scripts/seed_synthetic_ad.py` uses, adds each
to `Domain Users`, and writes generated passwords to a gitignored
`synthetic-users.env`:

```sh
./scripts/create_synthetic_users.sh
```

To do it by hand instead (e.g. one specific account):

```sh
docker compose exec samba-ad-dc samba-tool user create ad-synthetic-000 CHANGEME123 \
  --given-name="Synthetic" --surname="NocA" --department=NOC
docker compose exec samba-ad-dc samba-tool group addmembers "Domain Users" ad-synthetic-000
```

## When/if this gets wired in

If `platform/app/identity/` later queries this directly (LDAP bind +
search instead of the hardcoded fixture), it needs: an `ldap3`/`bonsai`
dependency, a read-only bind account (not `administrator`), and
`active-directory` added to `platform/docker-compose.yml`'s networks —
mirroring how `ZABBIX_API_TOKEN` is scoped read-only today. Until then,
treat this stack as available-but-inert.
