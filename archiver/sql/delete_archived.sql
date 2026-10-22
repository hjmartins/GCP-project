-- Apaga da Silver o que já foi arquivado. ts sem função no WHERE = DELETE por partição inteira (grátis).

DELETE FROM `{project}.{silver_dataset}.{silver_table}`
WHERE ts < TIMESTAMP(@cutoff)