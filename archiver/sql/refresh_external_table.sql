-- Recria a tabela externa da camada fria apontando para o metadata.json mais novo do Iceberg.
-- Placeholders preenchidos pelo archiver; DDL não é cobrado no BigQuery.
CREATE OR REPLACE EXTERNAL TABLE `{project}.{cold_dataset}.{cold_table}`
WITH CONNECTION `{connection}`
OPTIONS (
    format = 'ICEBERG',
    uris = ['{metadata_uri}']
);
