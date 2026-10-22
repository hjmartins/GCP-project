"""Experimentos 1, 2, 3 e 6 de FinOps (resultados em finops/experiments.md).

Pré-requisito: as cópias de teste da Silver (ver experiments.md, "Como reproduzir").
Rodar de dentro de loader/:  uv run python ../finops/run_experiments.py > resultados.json
Toda consulta vai sem cache e com teto de 600 MB faturados.
"""

import json, statistics, sys
from google.cloud import bigquery
c = bigquery.Client(project="telemetry-finops-hjm", location="us-central1")
CAP = 600_000_000  # teto por consulta: 600 MB

def run(sql, reps=1):
    out = []
    for _ in range(reps):
        j = c.query(sql, job_config=bigquery.QueryJobConfig(use_query_cache=False, maximum_bytes_billed=CAP))
        j.result()
        out.append(dict(processed=j.total_bytes_processed, billed=j.total_bytes_billed,
                        ms=int((j.ended - j.started).total_seconds() * 1000), slot_ms=j.slot_millis))
    return dict(processed=out[0]["processed"], billed=out[0]["billed"],
                ms=int(statistics.median(o["ms"] for o in out)), slot_ms=int(statistics.median(o["slot_ms"] or 0 for o in out)), reps=reps)

def dry(sql):
    j = c.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    return dict(processed=j.total_bytes_processed)

R = {}
W7 = "ts >= '2026-10-16' and ts < '2026-10-23'"
q1 = "select device_id, avg(heart_rate) fc, sum(steps) passos from `silver.{t}` where " + W7 + " group by 1"
for t in ["exp_readings_nopart", "exp_readings_part_noclust", "silver_readings"]:
    R[f"e1_{t}"] = run(q1.format(t=t), reps=3)

W30 = "ts >= '2026-09-23' and ts < '2026-10-23'"
q2 = "select date(ts) dia, avg(heart_rate) fc from `silver.{t}` where " + W30 + " and device_id = 'D00042' group by 1"
for t in ["exp_readings_part_noclust", "silver_readings"]:
    R[f"e2_{t}"] = run(q2.format(t=t), reps=3)

q3 = "select device_id, avg(heart_rate) fc, max(heart_rate) fc_max, sum(steps) passos, count(*) n from `{t}` where ts >= '{a}' and ts < '{b}' group by 1"
R["e3_hot_month"] = run(q3.format(t="silver.silver_readings", a="2026-09-01", b="2026-10-01"), reps=5)
R["e3_cold_month"] = run(q3.format(t="cold.readings", a="2026-06-01", b="2026-07-01"), reps=5)
q3b = "select date(ts) dia, avg(heart_rate) fc from `{t}` where ts >= '{a}' and ts < '{b}' and device_id = 'D00042' group by 1"
R["e3_hot_device"] = run(q3b.format(t="silver.silver_readings", a="2026-09-01", b="2026-10-01"), reps=5)
R["e3_cold_device"] = run(q3b.format(t="cold.readings", a="2026-06-01", b="2026-07-01"), reps=5)
R["e3_rows_hot_month"] = list(c.query("select count(*) n from silver.silver_readings where ts >= '2026-09-01' and ts < '2026-10-01'").result())[0].n
R["e3_rows_cold_month"] = list(c.query("select count(*) n from cold.readings where ts >= '2026-06-01' and ts < '2026-07-01'").result())[0].n

# E6: painel de 30 dias por cidade, a partir da Gold (tabela) e recalculado da Silver (o que uma view faria)
q6_table = """select u.cidade, g.metric_date, avg(g.steps) passos, avg(g.sleep_minutes) sono
from gold.gold_daily_user_metrics g join silver.silver_users u using (user_id)
where g.metric_date >= '2026-09-23' and g.metric_date < '2026-10-23' group by 1, 2"""
q6_view = """with device_day as (
  select r.device_id, date(r.ts) metric_date, sum(r.steps) steps
  from silver.silver_readings r where r.ts >= '2026-09-23' and r.ts < '2026-10-23' group by 1, 2),
sleep as (select device_id, date(inicio) metric_date, sum(duracao_min) sleep_minutes from silver.silver_sessions
  where tipo = 'sono' and inicio >= '2026-09-23' and inicio < '2026-10-23' group by 1, 2),
user_day as (select d.user_id, dd.metric_date, max(dd.steps) steps, max(s.sleep_minutes) sleep_minutes
  from device_day dd join silver.silver_devices d using (device_id) left join sleep s using (device_id, metric_date) group by 1, 2)
select u.cidade, ud.metric_date, avg(ud.steps) passos, avg(ud.sleep_minutes) sono
from user_day ud join silver.silver_users u using (user_id) group by 1, 2"""
R["e6_table"] = run(q6_table, reps=3)
R["e6_view"] = run(q6_view, reps=3)
json.dump(R, sys.stdout, indent=1)
