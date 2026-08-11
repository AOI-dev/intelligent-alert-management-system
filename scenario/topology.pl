% Scenario topology: the single source of truth for the synthetic world.
%
% This file is FACTS ONLY. All derivation lives in cascade.pl, so a second
% scenario is a second facts file loaded against the same rules -- that
% separation is the whole reason this is Prolog and not a YAML blob.
%
% Three consumers read this one file (see README.md):
%
%   1. the event generator  -- incidents and noise to emit into eventsim
%   2. the CMDB seed        -- services, hosts, ownership (today it is empty)
%   3. the scorer           -- ground truth: which alerts belong to which
%                              incident, and who should have been notified
%
% Keeping them on one file is deliberate: a generator and a scorer that
% disagree about the topology would silently produce meaningless metrics.

% ---------------------------------------------------------------------------
% Teams and users
% ---------------------------------------------------------------------------
% Multi-user filtering is a first-class scenario dimension, not an afterthought:
% "did the database on-call get paged for a frontend incident" is only
% answerable if the corpus knows who owns what.

% team(TeamId, DisplayName).
team(platform_infra, 'Platform Infrastructure').
team(payments,       'Payments').
team(storefront,     'Storefront').

% user(Login, TeamId, Role).
% Role is engineer (takes shifts) or manager (escalation target only, never
% the primary page).
user(alice,   platform_infra, engineer).
user(boris,   platform_infra, engineer).
user(galina,  platform_infra, manager).
user(carmen,  payments,       engineer).
user(dmitri,  payments,       engineer).
user(igor,    payments,       manager).
user(elena,   storefront,     engineer).
user(fyodor,  storefront,     engineer).
user(katya,   storefront,     manager).

% on_call(TeamId, Login, StartSeconds, EndSeconds).
% Who actually carries the pager, per team, over the corpus window. Pages are
% resolved against this by incident time -- NOT against a static role -- which
% is the sharpest CMDB/simulation coupling in the file: edit a shift boundary
% and the expected pages for every incident after it change. A scorer reading
% a stale rota would mark correct notifications as precision misses.
on_call(platform_infra, alice,  0,    3600).
on_call(platform_infra, boris,  3600, 7200).
on_call(payments,       carmen, 0,    3600).
on_call(payments,       dmitri, 3600, 7200).
on_call(storefront,     elena,  0,    3600).
on_call(storefront,     fyodor, 3600, 7200).

% escalates_to(TeamId, Login). Where an unacknowledged page goes next.
escalates_to(platform_infra, galina).
escalates_to(payments,       igor).
escalates_to(storefront,     katya).

% contact(Login, Channel, Address).
% Channel is trueconf | email | webhook. The webhook address is what a
% NotificationRequest.webhook_url would resolve to -- notifications/README.md
% notes no target registry exists yet, so this is the data that registry needs.
contact(alice,  trueconf, 'alice@tc.local').
contact(alice,  webhook,  'http://notify.local/hook/alice').
contact(boris,  trueconf, 'boris@tc.local').
contact(boris,  webhook,  'http://notify.local/hook/boris').
contact(carmen, trueconf, 'carmen@tc.local').
contact(carmen, webhook,  'http://notify.local/hook/carmen').
contact(dmitri, trueconf, 'dmitri@tc.local').
contact(dmitri, webhook,  'http://notify.local/hook/dmitri').
contact(elena,  trueconf, 'elena@tc.local').
contact(elena,  webhook,  'http://notify.local/hook/elena').
contact(fyodor, trueconf, 'fyodor@tc.local').
contact(fyodor, webhook,  'http://notify.local/hook/fyodor').
contact(galina, email,    'galina@corp.local').
contact(igor,   email,    'igor@corp.local').
contact(katya,  email,    'katya@corp.local').

% ---------------------------------------------------------------------------
% Services
% ---------------------------------------------------------------------------
% service(ServiceId, Tier, Criticality).
% Tier is edge | app | data. Criticality is critical | high | normal and is
% what a populated CMDB would carry; the filtering policy may read it, the
% generator never does.
service(storefront_web, edge, critical).
service(checkout,       app,  critical).
service(cart,           app,  high).
service(catalog,        app,  normal).
service(payments_api,   app,  critical).
service(sessions,       data, high).
service(db_primary,     data, critical).
service(db_replica,     data, high).
service(log_archive,    data, normal).

% owns(TeamId, ServiceId).
owns(storefront,     storefront_web).
owns(storefront,     cart).
owns(storefront,     catalog).
owns(payments,       checkout).
owns(payments,       payments_api).
owns(platform_infra, sessions).
owns(platform_infra, db_primary).
owns(platform_infra, db_replica).
owns(platform_infra, log_archive).

% ---------------------------------------------------------------------------
% Hosts
% ---------------------------------------------------------------------------
% host(Hostname, ServiceId). Hostname is what lands in MonitoringAlert.source,
% so these are the strings the platform actually sees. web-01/web-02/db-01/
% worker-03 are kept from eventsim/app/simulator.py's original _SOURCES so an
% existing corpus does not become unreadable.
host('web-01',     storefront_web).
host('web-02',     storefront_web).
host('checkout-01', checkout).
host('cart-01',    cart).
host('catalog-01', catalog).
host('pay-01',     payments_api).
host('pay-02',     payments_api).
host('sess-01',    sessions).
host('db-01',      db_primary).
host('db-02',      db_replica).
host('worker-03',  log_archive).

% site(Hostname, SiteId). Physical/AZ placement. A whole-site correlation
% ("everything in dc-b at once") is a different incident shape from a
% dependency cascade, and a filter should not confuse the two.
site('web-01',      'dc-a').
site('web-02',      'dc-b').
site('checkout-01', 'dc-a').
site('cart-01',     'dc-a').
site('catalog-01',  'dc-b').
site('pay-01',      'dc-a').
site('pay-02',      'dc-b').
site('sess-01',     'dc-a').
site('db-01',       'dc-a').
site('db-02',       'dc-b').
site('worker-03',   'dc-b').

% environment(ServiceId, Env). Everything here is prod except catalog's
% staging twin; a filter that pages on staging is losing precision for free.
environment(storefront_web, prod).
environment(checkout,       prod).
environment(cart,           prod).
environment(catalog,        prod).
environment(payments_api,   prod).
environment(sessions,       prod).
environment(db_primary,     prod).
environment(db_replica,     prod).
environment(log_archive,    staging).

% ---------------------------------------------------------------------------
% Configuration items
% ---------------------------------------------------------------------------
% ci(CiId, Type, Hostname).
%
% The object a metric is actually about. `cpu_percent` on db-01 is a reading
% from db-01's cpu CI, not from the host in the abstract -- and disk alerts in
% particular are per-volume, which is why one host can carry several.
%
% ENFORCED SYNC: validate/0 fails the run when any (host, metric) pair the
% generator could emit has no CI of the matching type. That check is the whole
% reason to declare these by hand rather than synthesising one CI per alert:
% a hand-written CMDB that has drifted from the simulation is exactly the
% failure this is meant to catch, and synthesising would hide it.

% metric_ci_type(Metric, CiType).
metric_ci_type(cpu_percent,       cpu).
metric_ci_type(disk_free_percent, disk_volume).
metric_ci_type(latency_ms,        endpoint).

ci('web-01/cpu',       cpu,         'web-01').
ci('web-01/http',      endpoint,    'web-01').
ci('web-02/cpu',       cpu,         'web-02').
ci('web-02/http',      endpoint,    'web-02').
ci('checkout-01/cpu',  cpu,         'checkout-01').
ci('checkout-01/http', endpoint,    'checkout-01').
ci('cart-01/cpu',      cpu,         'cart-01').
ci('cart-01/http',     endpoint,    'cart-01').
ci('cart-01/var',      disk_volume, 'cart-01').
ci('catalog-01/cpu',   cpu,         'catalog-01').
ci('catalog-01/http',  endpoint,    'catalog-01').
ci('pay-01/cpu',       cpu,         'pay-01').
ci('pay-01/http',      endpoint,    'pay-01').
ci('pay-02/cpu',       cpu,         'pay-02').
ci('pay-02/http',      endpoint,    'pay-02').
ci('sess-01/cpu',      cpu,         'sess-01').
ci('sess-01/http',     endpoint,    'sess-01').
ci('sess-01/cache',    cache,       'sess-01').
ci('db-01/cpu',        cpu,         'db-01').
ci('db-01/http',       endpoint,    'db-01').
ci('db-01/pgdata',     disk_volume, 'db-01').
ci('db-01/postgres',   db_instance, 'db-01').
ci('db-02/cpu',        cpu,         'db-02').
ci('db-02/http',       endpoint,    'db-02').
ci('db-02/pgdata',     disk_volume, 'db-02').
ci('db-02/postgres',   db_instance, 'db-02').
ci('worker-03/cpu',    cpu,         'worker-03').
ci('worker-03/archive', disk_volume, 'worker-03').
ci('worker-03/queue',  queue,       'worker-03').

% ---------------------------------------------------------------------------
% Maintenance windows
% ---------------------------------------------------------------------------
% maintenance_window(ServiceId, StartSeconds, EndSeconds).
%
% Ground truth for anything a service emits inside its own window is `noise`,
% however genuine the breach: planned work is not an incident. This is the one
% suppression signal in the corpus that is available ONLY from the CMDB -- it
% cannot be inferred from the alert stream at all -- so it is what distinguishes
% a CMDB-aware filter from a purely statistical one.
%
% Neither window currently covers an incident, keeping the headline metrics
% simple to read. Scheduling one over an incident is supported and handled
% (that incident then expects no page); do it deliberately, not by accident.
maintenance_window(catalog,     4800, 5400).
maintenance_window(log_archive, 6000, 6600).

% ---------------------------------------------------------------------------
% Dependencies
% ---------------------------------------------------------------------------
% depends_on(Dependent, Dependency): Dependent breaks when Dependency breaks.
% cascade.pl walks this transitively, so a root cause in db_primary surfaces
% as symptoms all the way out at storefront_web -- which is exactly the
% structure the i.i.d. simulator lacked and the correlator needs in order to
% have anything to correlate.
depends_on(storefront_web, cart).
depends_on(storefront_web, catalog).
depends_on(storefront_web, sessions).
depends_on(cart,           checkout).
depends_on(cart,           sessions).
depends_on(checkout,       payments_api).
depends_on(checkout,       db_primary).
depends_on(catalog,        db_replica).
depends_on(payments_api,   db_primary).
depends_on(sessions,       db_primary).
depends_on(db_replica,     db_primary).

% ---------------------------------------------------------------------------
% Trigger rules
% ---------------------------------------------------------------------------
% fires(RuleName, Metric, Comparison, Threshold, Severity).
%
% KNOWN COUPLING: this mirrors eventsim/app/rules.py. It is duplicated rather
% than imported because the generator must know which emitted values will
% actually fire a trigger before it emits them. If the two drift, the corpus
% silently stops firing and every metric reads as perfect filtering. The
% intended fix is to generate rules.py from here; until then, edit both.
%
% TIERS ARE REQUIRED, and eventsim/app/rules.py does not have them yet.
% FlapAwareCorrelator defines flapping as a signal recurring at a *lower
% severity* than before (app/core/correlation_automaton.py:_has_flapped).
% With one threshold per metric, severity is constant per signal and flapping
% is unrepresentable -- the corpus could never exercise the suppression path
% that already exists.
%
% CRITICAL: the tiers share ONE rule name per metric. Signal identity in the
% correlator is (rule, metric, source), so tier-specific rule names
% (high_cpu_warn vs high_cpu) would split each metric into two *separate*
% signals, each with a constant severity -- a regression is then never seen
% within a signal and flap detection still cannot fire. Worse, a genuine
% escalation would read as an unrelated new signal rather than an escalation.
% Severity is a property of the reading, not of the rule; MonitoringAlert
% carries the two as separate fields for exactly this reason.
%
% So rules.py needs severity tiers on its existing three rules -- not three
% additional rules.
fires(high_cpu,     cpu_percent,       gt, 75.0,   warning).
fires(high_cpu,     cpu_percent,       gt, 90.0,   critical).
fires(low_disk,     disk_free_percent, lt, 10.0,   warning).
fires(low_disk,     disk_free_percent, lt, 5.0,    critical).
fires(high_latency, latency_ms,        gt, 500.0,  warning).
fires(high_latency, latency_ms,        gt, 1000.0, critical).

% severity_rank(Severity, Rank). Mirrors SEVERITY_RANK in
% platform/app/core/correlation_automaton.py; used to pick the highest tier a
% value breaches, and to build flapping pairs that regress by rank.
severity_rank(resolved, 0).
severity_rank(info,     1).
severity_rank(warning,  2).
severity_rank(average,  3).
severity_rank(high,     4).
severity_rank(critical, 5).

% ---------------------------------------------------------------------------
% Incident catalogue
% ---------------------------------------------------------------------------
% root_cause(IncidentKind, ServiceId, Metric, Value, DurationSeconds).
%
% Value must breach the matching fires/5 threshold or the incident produces no
% alerts at all. Each kind names one originating service; cascade.pl derives
% every other alert the incident is responsible for.
root_cause(db_saturation,     db_primary,   cpu_percent,       97.0,   900).
root_cause(disk_exhaustion,   log_archive,  disk_free_percent, 3.0,    1800).
root_cause(payment_slowdown,  payments_api, latency_ms,        1400.0, 600).
root_cause(session_store_cpu, sessions,     cpu_percent,       94.0,   450).
root_cause(replica_lag,       db_replica,   latency_ms,        900.0,  1200).
root_cause(catalog_degraded,  catalog,      latency_ms,        1100.0, 700).
root_cause(checkout_errors,   checkout,     latency_ms,        1250.0, 500).

% propagates(RootMetric, DerivedMetric).
% How a dependency's symptom presents on the services above it. Saturation and
% disk pressure both surface upstream as latency -- the caller sees slowness,
% not the cause. This is precisely the inference the alert platform is supposed
% to make in reverse, so it must be structural in the corpus rather than
% signposted by a shared label.
propagates(cpu_percent,       latency_ms).
propagates(disk_free_percent, latency_ms).
propagates(latency_ms,        latency_ms).

% ---------------------------------------------------------------------------
% Noise
% ---------------------------------------------------------------------------
% noise_profile(Hostname, Metric, Pattern, PerHour).
%
% Ground truth for all of these is "noise": a correct filter emits zero
% notifications for them. Patterns are interpreted by the generator:
%
%   flapping  -- alternates breach/recover; the case FlapAwareCorrelator
%                already handles, included so the baseline arm has something
%                to score above zero
%   isolated  -- single unrelated breach, recovers on its own
%   chatty    -- identical repeat of one signal; the dedup case
noise_profile('worker-03',  cpu_percent,       flapping, 12).
noise_profile('catalog-01', latency_ms,        flapping, 6).
noise_profile('web-02',     cpu_percent,       isolated, 4).
noise_profile('cart-01',    disk_free_percent, isolated, 2).
noise_profile('db-02',      cpu_percent,       chatty,   20).
noise_profile('pay-02',     latency_ms,        chatty,   15).

% ---------------------------------------------------------------------------
% Timeline
% ---------------------------------------------------------------------------
% The corpus a scoring run replays. Offsets are seconds from corpus start;
% the generator's seed plus this list is what makes a run reproducible.
%
% timeline(OffsetSeconds, IncidentKind).
%
% Spread across owning teams on purpose. Per-user precision is only a real
% metric if more than one on-call is supposed to be paged over the corpus --
% with every incident rooted in platform_infra, "never page the wrong person"
% is satisfied by a filter that pages alice for everything.
timeline(120,   db_saturation).
timeline(900,   catalog_degraded).
timeline(1500,  payment_slowdown).
timeline(2400,  disk_exhaustion).
timeline(3000,  session_store_cpu).
timeline(3800,  checkout_errors).
timeline(4200,  replica_lag).
timeline(5400,  db_saturation).

% Total corpus length in seconds. Noise is generated across the whole span at
% each profile's PerHour rate, including the stretches with no incident -- a
% filter that only looks good during quiet periods is not a useful filter.
corpus_duration(7200).
