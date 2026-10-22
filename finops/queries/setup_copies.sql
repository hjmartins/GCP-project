-- Cópias de teste da Silver para os experimentos 1 e 2 (~0,5 GB faturados cada). Apagar depois.
create or replace table silver.exp_readings_nopart as
select * from silver.silver_readings where ts >= "2020-01-01";

create or replace table silver.exp_readings_part_noclust partition by date(ts) as
select * from silver.silver_readings where ts >= "2020-01-01";
