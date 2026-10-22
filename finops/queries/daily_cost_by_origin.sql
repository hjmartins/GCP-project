-- Bytes faturados por dia e por origem (pipeline × manual) no mês corrente.
select
  date(creation_time) as dia,
  if(starts_with(user_email, 'pipeline-runner'), 'pipeline', 'manual') as origem,
  count(*) as consultas,
  round(sum(total_bytes_billed) / pow(2, 30), 2) as gib_faturados,
  round(sum(total_bytes_billed) / pow(2, 40) * 6.25, 4) as usd_sem_free_tier
from `region-us-central1`.INFORMATION_SCHEMA.JOBS
where job_type = 'QUERY' and state = 'DONE'
  and creation_time >= timestamp_trunc(current_timestamp(), month)
group by 1, 2
order by 1, 2;
