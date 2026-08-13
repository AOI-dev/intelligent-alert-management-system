# platform/config

Bind-mounted read-only into the container at `/etc/platform`
(`docker-compose.yml`), which is what `ROUTING_CONFIG_PATH` points at.

`routing.json` lives here and is **gitignored** — it names real people and
real TrueConf accounts. Create it from `../routing.example.json`, or
generate one from a scenario corpus:

    cd platform && python3 -m scripts.routing_from_corpus ../scenario/corpus.json config/routing.json

`scripts/deploy.sh` rsyncs this directory to the VM like any other file in
the stack, so a routing.json created here reaches the deployment host —
gitignore keeps it out of git, not out of the deploy.

A missing `routing.json` is a supported state: `RoutingRegistry.from_file`
logs a warning and resolves nothing, so alerts keep being processed and
nobody is notified. That is why the *directory* is mounted rather than the
file — a bind mount of a nonexistent file makes Docker create a directory
with that name instead, which would turn a clear "not found" into a
confusing parse failure.
