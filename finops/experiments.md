# Experimentos de FinOps

Medidos em 2026-10-22 no projeto `telemetry-finops-hjm` (us-central1), com o pipeline em
produção: 250 dispositivos, Silver quente com 90 dias (6,08 milhões de leituras) e camada fria
Iceberg com 278 dias (18,46 milhões de leituras).

## Método

- **Consultas sem cache** (`use_query_cache = false`) e com teto de 600 MB faturados cada.
  Tempos são a **mediana** de 3 a 5 execuções. Script: [`run_experiments.py`](run_experiments.py).
- **Storage** medido nos metadados (`bq show`: bytes lógicos, físicos e de time travel) e, no
  Iceberg, pela soma de `file_size_in_bytes` dos arquivos da versão atual (PyIceberg).
- **Preços** oficiais de us-central1, lidos da Cloud Billing Catalog API (a mesma tabela usada
  no faturamento), **sem** free tier, para mostrar o custo real fora dele:

| Item | Preço |
| --- | --- |
| BigQuery consulta on-demand | US$ 6,25 por TiB (1 TiB/mês grátis) |
| BigQuery storage lógico ativo / long-term | US$ 0,023 / 0,016 por GiB/mês (10 GiB grátis) |
| BigQuery storage físico ativo / long-term | US$ 0,04 / 0,02 por GiB/mês (10 GiB grátis) |
| GCS Standard / Nearline / Coldline / Archive | US$ 0,020 / 0,010 / 0,004 / 0,0012 por GiB/mês (5 GiB Standard grátis) |
| GCS leitura Nearline / Coldline / Archive | US$ 0,01 / 0,02 / 0,05 por GiB lido |
| GCS permanência mínima Nearline / Coldline / Archive | 30 / 90 / 365 dias (cobrada se o arquivo sair antes) |

- **Projeção para escala:** 10 mil dispositivos = 40× o volume medido. São **projeções**,
  calculadas a partir dos bytes por linha medidos aqui, não medições.

## Resumo

| # | Experimento | Resultado medido | Conclusão |
| --- | --- | --- | --- |
| 1 | Particionamento | 7 dias: **195 MB** sem partição × **15,7 MB** particionada | 12× menos bytes; com 1 ano de dados a diferença cresce para ~50× |
| 2 | Clustering | filtro por dispositivo: 48,2 MB × 46,1 MB | **quase nenhum ganho** neste volume: partições de ~4 MB cabem num bloco só |
| 3 | Quente × frio | 1 mês: **65 MB nos dois**; 182 ms × **1.167 ms** | o frio não economiza na consulta e é 6× mais lento; a economia está no storage |
| 4 | Classe de storage | 2,36 GB de Iceberg (10 mil disp.): US$ 0,044 Standard × 0,014 Coldline por mês | Coldline economiza US$ 0,03/mês; não compensa a complexidade abaixo de dezenas de TB |
| 5 | Lógico × físico | Silver: **522 MB lógico × 93 MB físico** (US$ 0,011 × 0,0035/mês) | físico 3× mais barato, mesmo com time travel; é a **maior alavanca** do projeto |
| 6 | Tabela × view | 30 consultas/mês: tabela 1,89 GB × view 1,48 GB | hoje a view sai mais barata; a tabela vence acima de ~26–44 consultas/mês |

## 1. Particionamento

Mesma consulta (média de frequência cardíaca e passos por dispositivo em 7 dias) em três cópias
idênticas da Silver quente (6,08 milhões de linhas, 389 MB lógicos):

| Tabela | Processado | Faturado | Tempo |
| --- | --- | --- | --- |
| Sem partição | 194,6 MB | 195,0 MB | 302 ms |
| Particionada por dia | 14,9 MB | 15,7 MB | 229 ms |
| Particionada + cluster (`silver_readings`) | 14,9 MB | 15,7 MB | 218 ms |

A partição faz o BigQuery ler só os 7 dias pedidos (7/92 das partições). A sem partição leu a
tabela inteira, mas só as colunas usadas: por isso 195 MB e não 389 MB.

**Em escala:** sem partição, a mesma consulta leria o ano inteiro (~63 GB lógicos com 10 mil
dispositivos, ~US$ 0,36 por execução); particionada, ~0,6 GB (~US$ 0,004). É também por isso
que `silver_readings` exige filtro de partição: consulta sem filtro de data falha em vez de cobrar.

## 2. Clustering

Leituras de um dispositivo em 30 dias:

| Tabela | Processado | Faturado | Tempo | Slot-ms |
| --- | --- | --- | --- | --- |
| Particionada, sem cluster | 48,0 MB | 48,2 MB | 216 ms | 320 |
| Particionada + cluster por `device_id` | 45,3 MB | 46,1 MB | 180 ms | 202 |

Ganho de só 4% nos bytes. O clustering ordena os dados em **blocos** de storage e pula os blocos
que não têm o dispositivo, mas aqui cada partição diária tem ~4 MB e cabe em pouquíssimos blocos:
não há o que pular. O efeito aparece em partições grandes (dezenas de MB a GB por dia). Com
10 mil dispositivos (~170 MB por dia) o filtro por dispositivo deve ler uma fração da partição;
isso não foi medido aqui, então fica como expectativa, não como resultado.

O cluster continua valendo a pena: não tem custo de storage e já reduziu o trabalho (slot-ms) em
37%.

## 3. Quente × frio

O mesmo mês (2.005.920 leituras nos dois casos) consultado na Silver (setembro/2026) e na camada
fria Iceberg via BigLake (junho/2026):

| Consulta | Camada | Processado | Faturado | Tempo | Slot-ms |
| --- | --- | --- | --- | --- | --- |
| Agregado do mês por dispositivo | quente (BigQuery) | 64,2 MB | 65,0 MB | **182 ms** | 336 |
| | fria (Iceberg) | 64,2 MB | 65,0 MB | **1.167 ms** | 2.744 |
| Um dispositivo no mês | quente | 44,7 MB | 45,1 MB | 168 ms | 272 |
| | fria | 48,1 MB | 48,2 MB | 1.089 ms | 2.280 |

- **Os bytes cobrados são os mesmos.** O BigQuery cobra a tabela externa pelo tamanho lógico das
  colunas lidas, como uma tabela nativa. Consultar o frio não sai mais barato.
- **O frio é 6× mais lento e usa 8× mais processamento**: o BigQuery lê Parquet do GCS em vez do
  formato nativo dele. Continua abaixo de 1,2 s, aceitável para histórico.
- A partição por dia do Iceberg funciona: o mês leu 65 MB, não a tabela inteira (147 MB).

**A economia do frio está no storage**: o mesmo dado ocupa **64 bytes por linha** no BigQuery
(storage lógico, que é o cobrado por padrão) e **3,2 bytes** no Iceberg (Parquet com zstd): 20×
menos.

| 9 meses de histórico | Hoje (250 disp.) | 10 mil disp. |
| --- | --- | --- |
| No BigQuery, lógico long-term | US$ 0,018/mês | US$ 0,70/mês |
| No BigQuery, físico long-term | US$ 0,001/mês | US$ 0,04/mês |
| No Iceberg, GCS Standard | US$ 0,001/mês | US$ 0,044/mês |

**Decisão sobre o corte de 90 dias:** mantido.
- As consultas do painel olham os últimos 30 dias; tudo isso fica no quente, rápido.
- Aos 90 dias o BigQuery já passaria o dado para long-term (US$ 0,016); o Iceberg corta para o
  equivalente a ~US$ 0,001 por GiB lógico. Mover antes economizaria pouco e deixaria lenta a
  janela que o painel usa.
- **Ressalva importante:** com o storage **físico** (experimento 5), o BigQuery long-term custa
  praticamente o mesmo que o Iceberg. Nesse cenário a camada fria deixa de economizar dinheiro, e
  o motivo para mantê-la passa a ser o formato aberto (ler o histórico com Spark ou Trino sem
  passar pelo BigQuery).

## 4. Classe de storage do bucket frio (projeção)

O Iceberg da camada fria tem **59,0 MB** para 18,46 milhões de leituras (versão atual, sem as
versões antigas que a limpeza remove). Projeção para 12 meses com 10 mil dispositivos: **2,36 GB**
de dado frio, supondo que se leia 1 mês do histórico por mês:

| Classe | Armazenar | Ler 1 mês/mês | Total/mês |
| --- | --- | --- | --- |
| Standard | US$ 0,0440 | — | **US$ 0,044** |
| Nearline | US$ 0,0220 | US$ 0,0024 | US$ 0,024 |
| Coldline | US$ 0,0088 | US$ 0,0049 | **US$ 0,014** |
| Archive | US$ 0,0026 | US$ 0,0122 | US$ 0,015 |

- Coldline é a mais barata nesse padrão de uso; Archive perde porque cada leitura custa caro.
- A economia máxima é de **US$ 0,03 por mês**. Para valer o risco (taxa de permanência mínima
  quando o Iceberg reescreve arquivos, e a limpeza de versões apaga arquivos antes de 90 dias),
  o volume frio precisa estar na casa de dezenas de TB.
- **Decisão:** o bucket frio fica em Standard, que ainda está dentro do free tier (5 GiB).

## 5. Storage lógico × físico no BigQuery

O BigQuery cobra por padrão o tamanho **lógico** (descomprimido). O modelo **físico** cobra o
tamanho comprimido, a um preço por GiB maior, e inclui os bytes de time travel (dados alterados
ou apagados nos últimos 7 dias).

| Tabela (dataset `silver`) | Lógico | Físico | Físico: time travel |
| --- | --- | --- | --- |
| `silver_readings` | 389,1 MB | 79,4 MB | 61,3 MB |
| `silver_readings_quarantine` | 113,9 MB | 10,6 MB | 0,3 MB |
| `silver_sessions` | 18,7 MB | 2,9 MB | 0,2 MB |
| **Total** | **522 MB → US$ 0,011/mês** | **93 MB → US$ 0,0035/mês** | |

- Compressão medida: **21×** (64 bytes lógicos por linha × 3,0 físicos).
- Mesmo pagando o dobro por GiB e incluindo o time travel, o físico sai **3× mais barato**.
- O time travel de `silver_readings` (61 MB, mais que os 18 MB de dado vivo) vem do archiver: ele
  acabou de apagar 18 milhões de linhas, que ficam 7 dias em time travel. Reduzir a janela de
  time travel do dataset para 2 dias (`max_time_travel_hours = 48`) cortaria esse custo.

**Projeção, 10 mil dispositivos, 12 meses no BigQuery:** quente US$ 0,33 (lógico) × 0,03
(físico) por mês; frio US$ 0,70 × 0,04. **Trocar o modelo de cobrança do dataset é uma linha de
Terraform (`storage_billing_model = "PHYSICAL"`) e corta ~90% do custo de storage.** O Google só
permite trocar o modelo de um dataset uma vez a cada 14 dias.

## 6. Gold como tabela × como view

Painel típico: passos e sono médios por cidade e dia, últimos 30 dias, consultado 30× por mês.

| | Por consulta | 30 consultas/mês | Construção diária | Total/mês |
| --- | --- | --- | --- | --- |
| Tabela (`gold_daily_user_metrics`) | 0,2 MB processado, **21 MB faturados** | 0,63 GB | 41,9 MB/dia → 1,26 GB | **1,89 GB** |
| View (recalcula a partir da Silver) | 49,3 MB | **1,48 GB** | — | **1,48 GB** |

- **Hoje a view sai mais barata.** A consulta na tabela processa só 0,2 MB, mas o BigQuery cobra
  **no mínimo 10 MB por tabela** lida (duas tabelas = 21 MB), e a construção diária da tabela
  custa mais que as 30 consultas.
- O ponto de equilíbrio é ~44 consultas/mês hoje e ~26 com 10 mil dispositivos (a view cresce com
  o volume; a consulta na tabela não). Um painel aberto várias vezes por dia por um time passa
  disso fácil, e a tabela também responde 5× mais rápido em escala.
- **Decisão:** manter a Gold como tabela. Ela não serve só ao painel: é a base dos testes de
  qualidade e do bloqueio de publicação (Fase 5), e o custo absoluto é de centavos.

## Achados colaterais

- **O próprio monitoramento custa.** O `gold_cost_daily` fatura ~63 MB por dia, mais que a
  construção de qualquer outra tabela Gold, porque cada view de `INFORMATION_SCHEMA` é cobrada
  pelo mínimo de 10 MB.
- **A cobrança mínima de 10 MB por tabela** domina o custo de um pipeline com muitas consultas
  pequenas (6 modelos + 40 testes por dia): o dia a dia processa ~7 MB e fatura ~350 MB.
- **Backfill em lote:** 6,7 GB faturados em 47 consultas, contra ~130 GB estimados se fosse feito
  dia a dia (13 mil consultas, cada uma pagando o mínimo).
- **Iceberg externo exige limpeza ativa.** O `expire_snapshots` do PyIceberg só remove versões dos
  metadados; sem apagar os arquivos órfãos, o bucket frio chegou a 315 MB para 59 MB de dado útil.

## Como reproduzir

```bash
bq query --use_legacy_sql=false < finops/queries/setup_copies.sql      # ~1 GB faturado
cd loader && uv run python ../finops/run_experiments.py > ../finops/resultados.json
bq query --use_legacy_sql=false < finops/queries/teardown_copies.sql
```

Custo medido destes experimentos: **3,1 GB faturados** em 49 consultas (as duas cópias, os testes e as verificações), dentro do free tier: o mês fechou o dia 22/10 em 22,9 GB de 1 TB (2,3%).
