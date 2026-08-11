% Derivation rules over a scenario topology.
%
% This file contains NO scenario data -- it is loaded against topology.pl (or
% any other facts file with the same predicates). Everything a corpus needs is
% derived here: which services an incident reaches, what symptom each one
% shows, when, and -- the part that makes any of this measurable -- the ground
% truth saying which alerts belong to which incident and who should have been
% paged for it.
%
% Run:
%   swipl -g run -t halt cascade.pl -- --seed 42 --out corpus.json
%
% Ground truth here is derived, not asserted: an alert is `actionable` because
% a cascade rule produced it from a declared root cause. That is the property
% that makes the corpus worth scoring against -- nothing labels an alert
% "noise" by hand, so the labels cannot drift away from what was emitted.

% library(json), not library(http/json): the latter is the pre-SWI-9 location
% and now emits a "library was moved" warning on every run.
:- use_module(library(json)).
:- use_module(library(lists)).
:- use_module(library(apply)).
:- use_module(library(aggregate)).

:- ensure_loaded(topology).

actionable_dict(Dict) :- get_dict(gt, Dict, actionable).

% ---------------------------------------------------------------------------
% Timing constants
% ---------------------------------------------------------------------------

% Seconds a symptom takes to surface one dependency level up. Non-zero on
% purpose: if every alert in a cascade arrived at the same instant, ordering
% would carry no information and correlation would be a trivially easy problem.
hop_delay(45).

% While an incident is active its symptoms re-fire at this period. This is what
% creates storm and dedup pressure -- without repeats, a filter has nothing to
% collapse and "noise reduction" measures nothing.
repeat_interval(60).

% Spacing between the alerts making up one noise occurrence.
noise_spacing(30).

% ---------------------------------------------------------------------------
% Trigger evaluation
% ---------------------------------------------------------------------------

breach(gt, Value, Threshold) :- Value > Threshold.
breach(lt, Value, Threshold) :- Value < Threshold.

% severity_for(+Metric, +Value, -Rule, -Severity)
% The highest-severity tier this value breaches. Fails when nothing breaches,
% which is deliberate: a root_cause/5 value that fires no trigger is a scenario
% bug, and validate/0 turns that failure into a visible error rather than a
% silently short corpus.
severity_for(Metric, Value, Rule, Severity) :-
    findall(Rank-(R-S),
            ( fires(R, Metric, Cmp, Threshold, S),
              breach(Cmp, Value, Threshold),
              severity_rank(S, Rank) ),
            Matches),
    Matches \== [],
    max_member(_-(Rule-Severity), Matches).

% breach_value(+Metric, +Severity, -Value)
% A value that lands in a given tier, used to synthesise noise. Picks a point
% just past the tier's own threshold and short of the next one up.
breach_value(Metric, Severity, Value) :-
    fires(_, Metric, Cmp, Threshold, Severity),
    (   Cmp == gt
    ->  Value is Threshold * 1.05
    ;   Value is Threshold * 0.90
    ).

% ---------------------------------------------------------------------------
% Impact closure
% ---------------------------------------------------------------------------

% ph(+Root, ?Service, -Hops, +Seen)
% Service transitively depends on Root, Hops edges away. Seen guards against
% cyclic dependency declarations, which a topology file is free to contain.
ph(Root, Root, 0, _).
ph(Root, Service, Hops, Seen) :-
    Service \== Root,
    \+ memberchk(Service, Seen),
    depends_on(Service, Mid),
    ph(Root, Mid, Inner, [Service|Seen]),
    Hops is Inner + 1.

% impacted(+Root, ?Service, -Hops)
% Shortest path only: when a service reaches the root by several routes, the
% symptom shows up at the earliest one, not once per path.
impacted(Root, Service, Hops) :-
    service(Service, _, _),
    aggregate_all(min(H), ph(Root, Service, H, []), Hops).

% ---------------------------------------------------------------------------
% Symptom derivation
% ---------------------------------------------------------------------------

% derived_value(+Metric, +Hops, -Value)
% A symptom weakens as it propagates: the closer to the root, the worse it
% looks. Tuned so hop 1 still breaches the critical latency tier and deeper
% hops land in warning -- an incident should not present identically at every
% level, or severity carries no signal.
derived_value(latency_ms, Hops, Value) :-
    Value is 1500.0 / (1 + Hops * 0.35).
derived_value(Metric, _, Value) :-
    Metric \== latency_ms,
    breach_value(Metric, warning, Value).

% incident_id(+Kind, +Offset, -Id)
% Stable and readable: the same timeline entry always yields the same id, so
% two runs of the generator are diffable.
incident_id(Kind, Offset, Id) :-
    format(atom(Id), '~w@~w', [Kind, Offset]).

% incident_symptom(+Kind, +Offset, -Service, -Metric, -Value, -Hops)
% Every (service, symptom) pair one incident is responsible for: the root
% service showing the declared root-cause metric, plus each dependent service
% showing the propagated metric.
incident_symptom(Kind, _Offset, Service, Metric, Value, 0) :-
    root_cause(Kind, Service, Metric, Value, _).
incident_symptom(Kind, _Offset, Service, Derived, Value, Hops) :-
    root_cause(Kind, Root, Metric, _, _),
    impacted(Root, Service, Hops),
    Hops > 0,
    propagates(Metric, Derived),
    derived_value(Derived, Hops, Value).

% ---------------------------------------------------------------------------
% Incident alerts
% ---------------------------------------------------------------------------
%
% al(Time, Host, Service, Metric, Value, Severity, Rule, GroundTruth,
%    IncidentId, Hops) is the one alert term everything downstream reads.
% Time first so a plain msort/2 orders the corpus chronologically.

incident_alert(al(Time, Host, Service, Metric, Value, Severity, Rule,
                  actionable, IncidentId, Hops)) :-
    timeline(Offset, Kind),
    root_cause(Kind, _, _, _, Duration),
    incident_symptom(Kind, Offset, Service, Metric, Value, Hops),
    severity_for(Metric, Value, Rule, Severity),
    host(Host, Service),
    incident_id(Kind, Offset, IncidentId),
    hop_delay(HopDelay),
    Start is Offset + Hops * HopDelay,
    repeat_interval(Period),
    Last is Offset + Duration,
    between_by(Start, Last, Period, Time).

% between_by(+Low, +High, +Step, -X): Low, Low+Step, ... up to High.
between_by(Low, High, Step, X) :-
    Span is High - Low,
    Span >= 0,
    Count is Span // Step,
    between(0, Count, N),
    X is Low + N * Step.

% ---------------------------------------------------------------------------
% Noise alerts
% ---------------------------------------------------------------------------

% noise_alert(-Alert)
% Ground truth `noise` throughout: a correct filter emits zero notifications
% for every one of these. Timing is drawn from the seeded RNG set up in run/0.
noise_alert(al(Time, Host, Service, Metric, Value, Severity, Rule,
               noise, none, 0)) :-
    noise_profile(Host, Metric, Pattern, PerHour),
    host(Host, Service),
    corpus_duration(Duration),
    Occurrences is max(1, round(PerHour * Duration / 3600)),
    between(1, Occurrences, _),
    random_between(0, Duration, Start),
    pattern_step(Pattern, Metric, Index, Value, Severity),
    severity_for(Metric, Value, Rule, Severity),
    noise_spacing(Spacing),
    Time is Start + Index * Spacing.

% pattern_step(+Pattern, +Metric, -Index, -Value, -Severity)
% One occurrence expanded into its constituent alerts.
%
% flapping alternates critical/warning on the same signal, which is what
% FlapAwareCorrelator actually keys on -- a severity regression, not a
% recovery. Without the tiered fires/5 rules in topology.pl this pattern
% could not be expressed at all.
pattern_step(flapping, Metric, Index, Value, Severity) :-
    member(Index-Severity, [0-critical, 1-warning, 2-critical, 3-warning]),
    breach_value(Metric, Severity, Value).
pattern_step(isolated, Metric, 0, Value, warning) :-
    breach_value(Metric, warning, Value).
pattern_step(chatty, Metric, Index, Value, warning) :-
    between(0, 4, Index),
    breach_value(Metric, warning, Value).

% ---------------------------------------------------------------------------
% Expected notifications -- the scorer's target
% ---------------------------------------------------------------------------
%
% One page per incident, to the on-call of the team owning the ROOT service.
%
% This is the opinionated part of the whole corpus, so it is stated plainly:
% teams owning merely *impacted* services are deliberately not paged. A
% cascade from db_primary lights up storefront and payments dashboards, but
% waking three on-calls for one database problem is precisely the failure this
% platform exists to prevent. Per-user precision is measured against this, so
% loosening it would make the multi-user metric easier to score well on
% without the system having improved.
% on_call_at(+Team, +Time, -User)
% Resolved from the rota by time, not from a static role. Half-open interval
% so a shift boundary belongs to exactly one engineer.
on_call_at(Team, Time, User) :-
    on_call(Team, User, Start, End),
    Time >= Start,
    Time < End.

expected_page(IncidentId, Kind, RootService, Team, User, Escalation, Offset) :-
    timeline(Offset, Kind),
    root_cause(Kind, RootService, _, _, _),
    % An incident opening inside its own service's maintenance window is
    % planned work, and expects no page at all.
    \+ in_maintenance(RootService, Offset),
    owns(Team, RootService),
    on_call_at(Team, Offset, User),
    escalates_to(Team, Escalation),
    incident_id(Kind, Offset, IncidentId).

% ---------------------------------------------------------------------------
% Corpus assembly
% ---------------------------------------------------------------------------

% Alerts past the declared corpus length are dropped rather than clamped: a
% noise occurrence or incident tail that starts near the end would otherwise
% pile several alerts onto the final second, inventing a burst the scenario
% never described.
within_corpus(al(Time, _, _, _, _, _, _, _, _, _)) :-
    corpus_duration(Duration),
    Time =< Duration.

corpus_alerts(Sorted) :-
    findall(A, incident_alert(A), Incident),
    findall(A, noise_alert(A), Noise),
    append(Incident, Noise, All),
    include(within_corpus, All, Bounded),
    msort(Bounded, Sorted).

% ci_for(+Host, +Metric, -Ci)
% The configuration item a reading is actually about. Deliberately NOT
% synthesised when missing: validate/0 fails the run instead, because a
% silently invented CI is a CMDB that has drifted from the simulation without
% anyone noticing.
ci_for(Host, Metric, Ci) :-
    metric_ci_type(Metric, Type),
    ci(Ci, Type, Host).

in_maintenance(Service, Time) :-
    maintenance_window(Service, Start, End),
    Time >= Start,
    Time =< End.

% effective_gt(+Service, +Time, +Hops, +GroundTruth0, -GroundTruth, -Reason)
% Planned work outranks everything: a genuine breach inside a maintenance
% window is still not an incident, so an alert that would otherwise be
% actionable is demoted to noise. Reason is carried through so the scorer can
% report *why* something was noise -- "filtered 80%" is far less useful than
% knowing which of the three sources got filtered.
effective_gt(Service, Time, _, _, noise, maintenance) :-
    in_maintenance(Service, Time), !.
effective_gt(_, _, 0, actionable, actionable, root_cause) :- !.
effective_gt(_, _, _, actionable, actionable, cascade) :- !.
effective_gt(_, _, _, noise, noise, noise_profile).

alert_dict(al(T, Host, Service, Metric, Value, Severity, Rule, GT0, Inc, Hops),
           Dict) :-
    owns(Team, Service),
    environment(Service, Env),
    site(Host, Site),
    ci_for(Host, Metric, Ci),
    effective_gt(Service, T, Hops, GT0, GT, Reason),
    % An alert demoted by maintenance keeps no incident link: it is noise, and
    % leaving the id on it would let a scorer credit it toward incident recall.
    ( ( Inc == none ; GT == noise ) -> IncJson = null ; IncJson = Inc ),
    Rounded is round(Value * 100) / 100.0,
    Dict = _{ t: T, source: Host, service: Service, ci: Ci,
              metric: Metric, value: Rounded, severity: Severity, rule: Rule,
              gt: GT, gt_reason: Reason, incident_id: IncJson, hops: Hops,
              owner_team: Team, environment: Env, site: Site }.

incident_dict(Dict) :-
    expected_page(IncidentId, Kind, RootService, Team, User, Escalation, Offset),
    root_cause(Kind, _, _, _, Duration),
    Ends is Offset + Duration,
    Dict = _{ incident_id: IncidentId, kind: Kind, root_service: RootService,
              owner_team: Team, expected_page: User,
              escalates_to: Escalation,
              started_at: Offset, ends_at: Ends }.

% The same file that drives generation also seeds the CMDB, which is empty
% today. One source of truth: a CMDB that disagreed with the corpus would make
% every ownership-based metric meaningless -- so this is a projection of the
% same facts the generator read, never a parallel list.
cmdb_dict(_{ teams: Teams, users: Users, on_call: Shifts,
             services: Services, hosts: Hosts, cis: Cis,
             depends_on: Edges, maintenance: Windows }) :-
    findall(_{ id: T, name: N, escalates_to: E },
            ( team(T, N), escalates_to(T, E) ), Teams),
    findall(_{ login: L, team: T, role: R, contacts: Contacts },
            ( user(L, T, R),
              findall(_{ channel: C, address: A }, contact(L, C, A), Contacts) ),
            Users),
    findall(_{ team: T, login: L, from: S, to: E },
            on_call(T, L, S, E), Shifts),
    findall(_{ id: S, tier: Tier, criticality: C, owner_team: Team,
               environment: Env },
            ( service(S, Tier, C), owns(Team, S), environment(S, Env) ),
            Services),
    findall(_{ hostname: H, service: S, site: Site },
            ( host(H, S), site(H, Site) ), Hosts),
    findall(_{ id: Id, type: Type, hostname: H, service: S },
            ( ci(Id, Type, H), host(H, S) ), Cis),
    findall(_{ dependent: A, dependency: B }, depends_on(A, B), Edges),
    findall(_{ service: S, from: F, to: T },
            maintenance_window(S, F, T), Windows).

corpus(Seed, Corpus) :-
    corpus_alerts(Alerts),
    maplist(alert_dict, Alerts, AlertDicts),
    findall(D, incident_dict(D), Incidents),
    cmdb_dict(Cmdb),
    corpus_duration(Duration),
    length(AlertDicts, Total),
    include(actionable_dict, AlertDicts, Actionable),
    length(Actionable, ActionableCount),
    NoiseCount is Total - ActionableCount,
    Corpus = _{ seed: Seed, duration_seconds: Duration,
                alert_count: Total,
                actionable_count: ActionableCount,
                noise_count: NoiseCount,
                incidents: Incidents, alerts: AlertDicts, cmdb: Cmdb }.

% ---------------------------------------------------------------------------
% Validation
% ---------------------------------------------------------------------------
%
% Scenario bugs are silent by nature: a root cause whose value breaches no
% trigger simply contributes no alerts, and the run still "succeeds" with a
% corpus that quietly under-reports. These checks make that loud.

% check(+Goal, +FormatString, +Args): report and fail when Goal does not hold.
check(Goal, _, _) :- call(Goal), !.
check(_, Format, Args) :-
    format(user_error, 'SCENARIO ERROR: ', []),
    format(user_error, Format, Args),
    nl(user_error),
    fail.

% possible_signal(-Host, -Metric)
% Every (host, metric) pair the generator could ever emit, from both sources.
% The CMDB must cover all of them; this is what "in sync" is checked against.
possible_signal(Host, Metric) :-
    timeline(_, Kind),
    incident_symptom(Kind, _, Service, Metric, _, _),
    host(Host, Service).
possible_signal(Host, Metric) :-
    noise_profile(Host, Metric, _, _).

% contiguous(+SortedShifts, +From, +To): shifts exactly partition [From, To]
% -- no gap (nobody carrying the pager) and no overlap (two people paged).
contiguous([], X, X).
contiguous([Start-End|Rest], Start, To) :- contiguous(Rest, End, To).

validate :-
    forall(root_cause(Kind, _, Metric, Value, _),
           check(severity_for(Metric, Value, _, _),
                 'root_cause ~w value ~w on ~w breaches no trigger',
                 [Kind, Value, Metric])),
    forall(timeline(_, Kind),
           check(root_cause(Kind, _, _, _, _),
                 'timeline names unknown incident ~w', [Kind])),
    forall(service(S, _, _),
           check(owns(_, S), 'service ~w has no owner', [S])),
    forall(service(S, _, _),
           check(environment(S, _), 'service ~w has no environment', [S])),
    forall(host(H, S),
           check(service(S, _, _), 'host ~w names unknown service ~w', [H, S])),
    forall(host(H, _),
           check(site(H, _), 'host ~w has no site', [H])),
    forall(ci(Id, _, H),
           check(host(H, _), 'ci ~w names unknown host ~w', [Id, H])),

    % The CMDB/simulation sync check this file exists for. A metric the
    % generator emits with no CI behind it means the CMDB has drifted, and
    % every CI-scoped metric computed afterwards would be quietly wrong.
    forall(possible_signal(Host, Metric),
           check(ci_for(Host, Metric, _),
                 'no CI on host ~w for metric ~w (CMDB out of sync with the simulation)',
                 [Host, Metric])),
    forall(possible_signal(_, Metric),
           check(metric_ci_type(Metric, _),
                 'metric ~w maps to no CI type', [Metric])),

    % Rota and contacts: a page with nobody to send it to, or two people
    % on call at once, breaks per-user precision before scoring starts.
    forall(team(T, _),
           check(escalates_to(T, _), 'team ~w has no escalation contact', [T])),
    forall(user(L, _, engineer),
           check(contact(L, webhook, _),
                 'engineer ~w has no webhook contact to notify', [L])),
    forall(team(T, _),
           check(( findall(S-E, on_call(T, _, S, E), Shifts),
                   msort(Shifts, Sorted),
                   corpus_duration(D),
                   contiguous(Sorted, 0, D) ),
                 'team ~w on-call shifts do not exactly cover 0..corpus_duration (gap or overlap)',
                 [T])),
    forall(( timeline(Offset, Kind), root_cause(Kind, Root, _, _, _),
             \+ in_maintenance(Root, Offset) ),
           check(aggregate_all(count,
                               expected_page(_, Kind, _, _, _, _, Offset), 1),
                 'incident ~w at ~w does not resolve to exactly one on-call engineer',
                 [Kind, Offset])),

    forall(maintenance_window(S, From, To),
           check(( corpus_duration(D), From >= 0, To =< D, From < To ),
                 'maintenance window on ~w (~w..~w) is outside 0..corpus_duration or inverted',
                 [S, From, To])).

% ---------------------------------------------------------------------------
% Entry point
% ---------------------------------------------------------------------------

run :-
    current_prolog_flag(argv, Argv),
    ( option_value(Argv, '--seed', SeedAtom) -> atom_number(SeedAtom, Seed) ; Seed = 42 ),
    ( option_value(Argv, '--out', Out) -> true ; Out = 'corpus.json' ),
    (   validate
    ->  true
    ;   format(user_error, 'scenario validation failed; no corpus written~n', []),
        halt(1)
    ),
    set_random(seed(Seed)),
    corpus(Seed, Corpus),
    setup_call_cleanup(
        open(Out, write, Stream),
        json_write_dict(Stream, Corpus, [width(0)]),
        close(Stream)),
    length(Corpus.incidents, IncidentCount),
    format('wrote ~w: ~w alerts (~w actionable, ~w noise), ~w incidents, seed ~w~n',
           [Out, Corpus.alert_count, Corpus.actionable_count,
            Corpus.noise_count, IncidentCount, Seed]).

option_value([Flag, Value|_], Flag, Value) :- !.
option_value([_|Rest], Flag, Value) :- option_value(Rest, Flag, Value).
