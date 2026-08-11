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

Finally, install the apache drop-in this stack's nginx depends on (see
"The API layer needs its own telling" below):

```sh
ssh vm "bash ~/trueconf-tls/install-tcs-vhost.sh"
```

## After this is up

Point `platform/flags.env`'s `TRUECONF_BASE_URL` at
`https://161.104.107.172:8443` instead of the plain-HTTP address. A
plain-HTTP `TRUECONF_OAUTH_REDIRECT_URI` is fine — checked live, TrueConf
validates credentials without complaining about it, so only the TrueConf
side of the flow needs to be HTTPS, not `platform`'s callback.

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

## The API layer needs its own telling, too

With TLS up *and* `[proxy]` enabled, the `/oauth2/authorize` page loads —
and then the login form itself fails, the browser showing

```json
{"error":{"code":400,"message":"Bad Request",
          "errors":[{"reason":"insecureConnection"}]}}
```

from `POST /api/v4/oauth2/auth`. `[proxy]` fixes the page; it does not
fix that API. What that endpoint (TrueConf's Go manager, `bin/manager`)
looks at is the **`X-Forwarded-SSL`** header — narrowed down by hand
against the manager on `127.0.0.1:1337`, where sending `X-Forwarded-SSL:
on` is the single difference between `insecureConnection` and ordinary
`missingRequiredField` validation. `X-Forwarded-Proto`,
`X-Forwarded-Protocol`, `X-Url-Scheme` and a matching `Host` are all
ignored for this check.

TLS at this stack's nginx can't supply it, no matter what it sets:
TrueConf's own front-end vhost does

```apache
RequestHeader set "X-Forwarded-SSL" expr=%{HTTPS}
```

which overwrites whatever the front proxy sent with apache's own view of
*its* listener — plain HTTP, so `off`.

Fix (confirmed live): `install-tcs-vhost.sh` copies
`tcs/xforwarded-ssl-vhost.conf` into the running container at
`/opt/trueconf/server/opt2/` and restarts the `trueconf-web` supervisor
program. That file is a copy of TrueConf's own catch-all vhost on port
**8081**, differing only in reporting the TLS this stack really
terminates instead of deriving it from its own listener; `nginx.conf`
proxies to `:8081` instead of `:80`. 8081 is not published on the host,
so only containers on this stack's docker network can reach it — the
public `:80` vhost is untouched and still reports itself insecure, which
is why asserting `X-Forwarded-SSL: on` from outside doesn't get anyone
past TrueConf's check.

Same caveats as the `manager.toml` edit above: it lives in the
container's own filesystem rather than a bind mount (which would mean
recreating the container — ruled out in `trueconf/README.md`), so
**re-run `install-tcs-vhost.sh` if `trueconf-server` is ever recreated.**
The script is idempotent, syntax-checks the config before restarting
apache, and removes the drop-in again if apache rejects it.

## The callback has to live on the TrueConf origin, and so does the frontend

TrueConf's login SPA finishes the flow from JavaScript, not with a plain
form POST:

```js
.then(n => document.location.href = n.request.responseURL + "&state=" + state)
.catch(({response: n}) => { if (!n) { document.location.href = currentClient.redirect_uri; return } … })
```

Two consequences, both hit in practice:

- **`redirect_uri` must be same-origin with the login page.** It's read
  off an XHR's `responseURL`, so a plain-HTTP `redirect_uri` makes that a
  mixed-content request the browser kills before it's sent. The SPA then
  takes its `if (!n)` branch and bounces the browser to the *bare*
  `redirect_uri` — no `code`, no `state`, which looks exactly like the
  platform callback rejecting a malformed request. Hence `nginx.conf`
  serving `/v1/auth/callback` off this origin, proxied to
  monitoring-platform, and `TRUECONF_OAUTH_REDIRECT_URI` pointing at
  `https://…:8443/v1/auth/callback`. **The redirect_uri registered for
  the OAuth2 app in TrueConf's control panel must match it exactly.**
- **TrueConf drops `state`.** The callback arrives as a bare
  `?code=…`; the SPA is what re-appends state, from a store that isn't
  populated on this path. platform therefore also stashes the signed
  state in a cookie during `/v1/auth/login` and falls back to it (see
  `platform/app/identity/router.py`).

That cookie is why **the frontend is also served here, on `:8543`**.
Browsers compute "same site" *schemefully*: a page on `http://…:8091`
and a callback on `https://…:8443` are cross-site despite sharing a host,
and a `SameSite=Lax` cookie set by the former doesn't come back on the
latter. One scheme end to end fixes it, so use

```
https://161.104.107.172:8543/
```

as the app's entry point (one click-through cert warning per port —
:8443 and :8543 are separate as far as the browser is concerned). The
plain-HTTP `http://…:8091` frontend still works for everything except
completing a login.

## Renewing / regenerating the cert

`gen-cert.sh` refuses to overwrite an existing `certs/tls.crt`. To
regenerate (e.g. the VM's IP changes): `rm certs/tls.*` first, then rerun
it, then `docker compose up -d --build` to bake the new cert into a fresh
image (nginx doesn't hot-reload a cert baked in at build time).
