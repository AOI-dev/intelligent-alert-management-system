# trueconf-tls

A self-signed HTTPS front door for `trueconf-server`, and nothing else.

## Why this exists

TrueConf Server's OAuth2 `/oauth2/authorize` step refuses to run over
plain HTTP ("Authorization requires HTTPS to ensure your data safety").
`trueconf-server`'s own HTTPS port (443) was never actually configured
with a certificate (see `trueconf/README.md` — its webmanager dir, where
TLS certs would live, was deliberately never mounted) and doesn't serve
anything real; confirmed live from the VM itself
(`curl https://localhost/` fails to connect, `curl http://localhost/`
returns 200).

## Why this is a separate stack instead of fixing `trueconf-server` directly

`trueconf/README.md` is explicit: recreating that container (which adding
a TLS cert/mounting its webmanager dir would require — Docker volume
mounts are fixed at container creation) risks invalidating the TrueConf
license. This stack never touches `trueconf-server`'s own container,
image, ports, or volumes — it's a completely separate nginx container that
terminates TLS and forwards plain HTTP to `trueconf-server` internally.
The one interaction with `trueconf-server` is additive and non-disruptive:
`docker network connect` attaches an *already-running* container to an
*additional* network without recreating it — its original ports, volumes,
and license state are untouched.

No real certificate is possible here: this VM has no domain name, only a
bare IP (`161.104.107.172`), and no public CA (Let's Encrypt included)
issues certificates for bare IPs. Every visitor gets a one-time browser
warning to click through — expected, not a bug, and not fixable without a
domain name pointed at this VM.

## One-time setup

```sh
cd trueconf-tls
./gen-cert.sh 161.104.107.172   # writes certs/tls.{crt,key}, gitignored
```

Then deploy as usual (`scripts/deploy.sh trueconf-tls trueconf-tls` from
the repo root) — but `gen-cert.sh` must be run **on the deploy host**
(the VM), after syncing, before the first `docker compose up --build`:
`certs/` is gitignored like every other secret-shaped thing in this repo,
so it's never synced by `deploy.sh`'s rsync (which excludes only `.env` by
default — `certs/` is excluded via the root `.gitignore` pattern instead).

```sh
ssh vm
cd ~/trueconf-tls
./gen-cert.sh 161.104.107.172
docker compose up -d --build
```

Then, **once**, attach the already-running `trueconf-server` to this
stack's network (see "Why this is a separate stack" above for why this is
safe and the container recreation isn't):

```sh
docker network connect trueconf-tls_trueconf-tls trueconf-server
```

## After this is up

Point `platform/flags.env`'s `TRUECONF_BASE_URL` at
`https://161.104.107.172:8443` instead of the plain-HTTP address. Login
starts working from there; if TrueConf *also* rejects a plain-HTTP
`TRUECONF_OAUTH_REDIRECT_URI` (unconfirmed as of writing — the error seen
so far was specifically about the `/oauth/authorize` step), `platform`
itself would need the same treatment, which this stack doesn't attempt to
predict or solve preemptively.

## TLS alone isn't enough — TrueConf must also be told it's behind a proxy

Getting this stack up still left `/oauth/authorize` failing with
"Authorization requires HTTPS" even when the browser was on
`https://161.104.107.172:8443`. Cause: `trueconf-server`'s own
`/opt/trueconf/server/etc/manager/manager.toml` has a `[proxy]` section
that defaults to `enabled = false`. With it disabled, TrueConf builds its
notion of the request's scheme from what it *itself* received — plain
HTTP from this stack's nginx — regardless of what the browser actually
used, so the HTTPS check fails no matter how solid the front-door TLS is.

Fix (confirmed live): inside the running container —

```sh
docker exec trueconf-server sed -i \
  "s/address = 'localhost:8443'/address = '161.104.107.172:8443'/; s/enabled = false/enabled = true/" \
  /opt/trueconf/server/etc/manager/manager.toml
docker exec trueconf-server supervisorctl restart trueconf-manager
```

This restarts only the `trueconf-manager` supervisor process, not the
container — same license-safety property as `trueconf/start.sh`. This
file lives in the container's own filesystem, not a host bind mount (see
`trueconf/README.md` — the webmanager/etc dir is deliberately unmounted),
so there's no way to author it locally first; **it will need to be
reapplied if `trueconf-server` is ever recreated** (`remove.sh` + fresh
`run.sh`, an image update, etc.) since nothing here persists it.

## Renewing / regenerating the cert

`gen-cert.sh` refuses to overwrite an existing `certs/tls.crt`. To
regenerate (e.g. the VM's IP changes): `rm certs/tls.*` first, then rerun
it, then `docker compose up -d --build` to bake the new cert into a fresh
image (nginx doesn't hot-reload a cert baked in at build time).
