#!/usr/bin/env python3
"""Расчёт финансово-экономической модели.

Единственный источник чисел для главы «Экономика». Все допущения заданы
константами ниже; результат печатается в том виде, в каком он попадает в
таблицы документа, плюс готовые строки LaTeX.

Запуск:  python3 context/economics.py
         python3 context/economics.py --tex   (только строки для таблиц)
"""
from __future__ import annotations

import sys

# ---------------------------------------------------------------- вводные
# Обязательные ставки кейса (IT CAMP, дерево КПЭ)
FTE_RATE = 2_000          # руб./ч — стоимость FTE, для расчёта эффектов
TEAM_RATE = 3_500         # руб./ч — стоимость часа проектной команды, для затрат
DOWNTIME_COST_DAY = 150_000_000   # руб./сут. — простой установки НПЗ

# Измерено на эталонном корпусе (scenario/corpus.json, seed 42)
CORPUS_ALERTS = 1053
CORPUS_HOURS = 2
PAGES_BASE = 1053         # уведомлений без фильтрации
PAGES_CORRELATOR = 44     # уведомлений с корреляцией
PAGES_PER_INCIDENT_BASE = 131.6
PAGES_PER_INCIDENT_NEW = 5.5

# Допущения (обоснование — в таблице документа)
REACTION_MIN = 2          # мин на разбор одного уведомления
SHIFTS = 2                # дежурных смен
SHIFT_HOURS = 8           # часов в смене
TRIAGE_SHARE = 0.30       # доля времени дежурного на разбор оповещений
RELEASED_SHARE = 0.70     # какая доля этого времени высвобождается
INCIDENTS_PER_YEAR = 6    # значимых инцидентов с простоем в год
MTTA_SAVED_MIN = 15       # мин сокращения обнаружения и адресации на инцидент

TEAM_SIZE = 6             # человек в проектной команде
PROJECT_WEEKS = 8         # недель разработки пилота
WEEK_HOURS = 40
SUPPORT_HOURS_MONTH = 30  # ч/мес сопровождения

INFRA_MONTH = {           # руб./мес., аренда узлов
    "Приложения (4 vCPU, 8 ГБ)": 6_000,
    "Данные и шина (8 vCPU, 16 ГБ)": 12_000,
    "ИИ, GPU (8 vCPU, 32 ГБ)": 45_000,
}
INFRA_AI_KEY = "ИИ, GPU (8 vCPU, 32 ГБ)"

DISCOUNT_RATE = 0.20
HORIZON_YEARS = 3

M = 1_000_000             # для перевода в млн руб.


# ------------------------------------------------------------- вычисления
def compute() -> dict:
    downtime_cost_hour = DOWNTIME_COST_DAY / 24

    # --- уровень 4 -> уровень 3 ---
    alerts_per_day = round(CORPUS_ALERTS * 24 / CORPUS_HOURS)
    pages_per_day = round(PAGES_CORRELATOR * 24 / CORPUS_HOURS)
    noise_reduction = 1 - PAGES_CORRELATOR / PAGES_BASE

    # 3.1 трудозатраты: эффект ограничен фактическим фондом времени дежурных
    naive_hours_day = (alerts_per_day - pages_per_day) * REACTION_MIN / 60
    fund_hours_day = SHIFTS * SHIFT_HOURS
    triage_hours_day = fund_hours_day * TRIAGE_SHARE
    released_hours_day = triage_hours_day * RELEASED_SHARE
    labor_base_year = triage_hours_day * 365
    labor_target_year = (triage_hours_day - released_hours_day) * 365
    labor_saved_year = released_hours_day * 365

    # 3.2 время простоя
    downtime_saved_year = INCIDENTS_PER_YEAR * MTTA_SAVED_MIN / 60

    # --- уровень 2 ---
    effect_labor = labor_saved_year * FTE_RATE
    effect_downtime = downtime_saved_year * downtime_cost_hour
    effect_total = effect_labor + effect_downtime

    # --- затраты ---
    project_hours = TEAM_SIZE * PROJECT_WEEKS * WEEK_HOURS
    capex = project_hours * TEAM_RATE
    support_year = SUPPORT_HOURS_MONTH * 12 * TEAM_RATE
    infra_year = sum(INFRA_MONTH.values()) * 12
    infra_ai_year = INFRA_MONTH[INFRA_AI_KEY] * 12
    opex = support_year + infra_year

    # --- уровень 1 ---
    net = effect_total - opex
    flows: list[float] = [-float(capex)]
    discounted: list[float] = [-float(capex)]
    cumulative: list[float] = [-float(capex)]
    for year in range(1, HORIZON_YEARS + 1):
        d = net / (1 + DISCOUNT_RATE) ** year
        flows.append(net)
        discounted.append(d)
        cumulative.append(cumulative[-1] + d)
    pv = sum(discounted[1:])
    npv = pv - capex
    pi = pv / capex

    dpp = None
    for year in range(1, HORIZON_YEARS + 1):
        if cumulative[year] >= 0:
            prev = cumulative[year - 1]
            dpp = (year - 1) + (-prev) / discounted[year]
            break

    # --- чувствительность ---
    net_wo_labor = (effect_total - effect_labor) - opex
    pv_wo_labor = sum(net_wo_labor / (1 + DISCOUNT_RATE) ** y for y in range(1, HORIZON_YEARS + 1))
    npv_wo_labor = pv_wo_labor - capex
    breakeven_hours = (capex + opex) / downtime_cost_hour

    return dict(
        downtime_cost_hour=downtime_cost_hour,
        alerts_per_day=alerts_per_day, pages_per_day=pages_per_day,
        noise_reduction=noise_reduction, naive_hours_day=naive_hours_day,
        fund_hours_day=fund_hours_day, triage_hours_day=triage_hours_day,
        released_hours_day=released_hours_day,
        labor_base_year=labor_base_year, labor_target_year=labor_target_year,
        labor_saved_year=labor_saved_year, downtime_saved_year=downtime_saved_year,
        effect_labor=effect_labor, effect_downtime=effect_downtime, effect_total=effect_total,
        project_hours=project_hours, capex=capex, support_year=support_year,
        infra_year=infra_year, infra_ai_year=infra_ai_year, opex=opex,
        net=net, flows=flows, discounted=discounted, cumulative=cumulative,
        pv=pv, npv=npv, pi=pi, dpp=dpp,
        npv_wo_labor=npv_wo_labor, breakeven_hours=breakeven_hours,
    )


def report(r: dict) -> None:
    print("=== Вводные ===")
    print(f"стоимость часа простоя           {r['downtime_cost_hour']/M:.2f} млн руб./ч")
    print(f"поток алертов                    {r['alerts_per_day']} шт./сут.")
    print(f"уведомлений после обработки      {r['pages_per_day']} шт./сут.")
    print(f"снижение шума                    {r['noise_reduction']*100:.1f} %")

    print("\n=== Уровень 3: физические параметры ===")
    print(f"прямой (неверный) счёт           {r['naive_hours_day']:.0f} чел.-ч/сут.")
    print(f"фонд дежурных                    {r['fund_hours_day']:.0f} чел.-ч/сут.")
    print(f"из них на разбор                 {r['triage_hours_day']:.1f} чел.-ч/сут.")
    print(f"высвобождается                   {r['released_hours_day']:.2f} чел.-ч/сут.")
    print(f"3.1 трудозатраты: база -> цель   {r['labor_base_year']:.0f} -> {r['labor_target_year']:.0f} чел.-ч/год")
    print(f"    сокращение                   {r['labor_saved_year']:.0f} чел.-ч/год")
    print(f"3.2 простой: сокращение          {r['downtime_saved_year']:.2f} ч/год")

    print("\n=== Уровень 2: операционные КПЭ ===")
    print(f"2.1 сокращение трудозатрат       {r['effect_labor']/M:.2f} млн руб./год")
    print(f"2.2 снижение потерь от простоя   {r['effect_downtime']/M:.2f} млн руб./год")
    print(f"    суммарный эффект             {r['effect_total']/M:.2f} млн руб./год")

    print("\n=== Затраты ===")
    print(f"трудоёмкость пилота              {r['project_hours']} ч ({TEAM_SIZE} чел. x {PROJECT_WEEKS} нед.)")
    print(f"разовые                          {r['capex']/M:.2f} млн руб.")
    print(f"сопровождение                    {r['support_year']/M:.2f} млн руб./год")
    print(f"инфраструктура                   {r['infra_year']/M:.2f} млн руб./год "
          f"(доля ИИ-узла {r['infra_ai_year']/r['infra_year']*100:.0f} %)")
    print(f"инфраструктура без ИИ            {(r['infra_year']-r['infra_ai_year'])/M:.2f} млн руб./год")
    print(f"периодические итого              {r['opex']/M:.2f} млн руб./год")

    print("\n=== Уровень 1: инвестиционные КПЭ ===")
    print(f"чистый поток года                {r['net']/M:.2f} млн руб.")
    print("год           " + "".join(f"{y:>10}" for y in range(0, HORIZON_YEARS + 1)))
    print("поток         " + "".join(f"{v/M:>10.1f}" for v in r['flows']))
    print("дисконт.поток " + "".join(f"{v/M:>10.1f}" for v in r['discounted']))
    print("накопленный   " + "".join(f"{v/M:>10.1f}" for v in r['cumulative']))
    print(f"PV  = {r['pv']/M:.2f} млн руб.")
    print(f"NPV = {r['npv']/M:.2f} млн руб.")
    print(f"PI  = {r['pi']:.2f}")
    print(f"DPP = {r['dpp']:.2f} года ({r['dpp']*12:.0f} мес.)")

    print("\n=== Чувствительность ===")
    print(f"NPV без эффекта 2.1              {r['npv_wo_labor']/M:.2f} млн руб.")
    print(f"часов простоя для окупаемости    {r['breakeven_hours']:.2f} ч (затраты первого года "
          f"{(r['capex']+r['opex'])/M:.1f} млн руб.)")


def tex(r: dict) -> None:
    print("% строки для таблицы ФЭМ (млн руб.)")
    names = ["Чистый поток", "Дисконтированный поток", "Накопленный дисконт. поток"]
    for name, row in zip(names, [r['flows'], r['discounted'], r['cumulative']]):
        cells = " & ".join(f"{v/M:.1f}".replace('.', ',').replace('-', '$-$') for v in row)
        print(f"{name} & {cells} \\\\ \\hline")
    print(f"% NPV {r['npv']/M:.1f} | PV {r['pv']/M:.1f} | PI {r['pi']:.1f} | DPP {r['dpp']:.1f}")


if __name__ == "__main__":
    result = compute()
    if "--tex" in sys.argv:
        tex(result)
    else:
        report(result)
