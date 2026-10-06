# Testbench report

Generated 2026-10-06T10:08:34+00:00 from 184 run(s). Raw data: `results.csv`, `runs/*/result.json`.

`*` = every run of this cell was interrupted (provider outage/stall); the best attempt is shown as a lower bound.

## Agent comparison (gateway runs)

All agents run the same pinned model through saia_gateway.py. DeepSWE cells: reward (median of valid runs) / mean F2P pass fraction / median requests. In-house cells: hidden-test pass rate / — / median requests. `inv` = only invalid runs.

| task | pi-ds |
|---|---|
| deepswe-true-myth-iterable-collection-combinators | 100% / 100% / 65 |

| combo | agent | valid/all | mean reward | mean F2P | solves per 1k requests | median wall s | median prompt tok/request | flags seen |
|---|---|---|---|---|---|---|---|---|
| pi-ds | pi | 1/1 | 100% | 100% | 15.4 | 2179.2 | 89882 | — |

## API requests per task × combo

Median SAIA requests actually charged per run (gateway upstream attempts, or the budget-counter delta for legacy runs; includes failed/5xx requests). `~N` = LLM-response count fallback when no budget snapshot bracketed the run; `(i)` = interrupted lower-bound cell.

| task | pi-ds | planbuild | planbuild-ds4-coder | planbuild-dsv4 | planbuild-p_coder-b_coder | planbuild-p_coder-b_dsv4 | planbuild-p_coder-b_glm47 | planbuild-p_coder-b_qwen36 | planbuild-p_mistral-b_coder | planbuild-p_mistral-b_dsv4 | planbuild-p_mistral-b_glm47 | planbuild-p_mistral-b_qwen36 | planbuild-p_qwen35-b_coder | planbuild-p_qwen35-b_dsv4 | planbuild-p_qwen35-b_glm47 | planbuild-p_qwen35-b_qwen36 | plansolo | solo | solo-coder | solo-dsv4 | solo-qwen35 | solo-qwen36 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| csv-bugfix | — | 25 (i) | 43 (i) | 190 | ~35 (i) | ~33 (i) | ~15 (i) | ~26 (i) | — | — | — | — | — | — | — | — | 20 (i) | — | — | 26 (i) | — | — |
| deepswe-true-myth-iterable-collection-combinators | 77 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| minilang | — | 7 (i) | 12 (i) | 19 (i) | 77 (i) | 18 (i) | 57 (i) | 76 (i) | 18 (i) | 51 (i) | 18 (i) | 11 (i) | 39 (i) | 17 (i) | 45 (i) | 14 (i) | — | — | — | — | — | — |
| minilang2 | — | 129 (i) | 28 (i) | 26 | 5 (i) | 118 (i) | 16 (i) | 23 (i) | 24 (i) | 129 (i) | 117 (i) | 61 (i) | 23 (i) | 82 (i) | 34 (i) | 15 (i) | — | ~162 (i) | 131 (i) | ~120 (i) | ~25 (i) | ~52 (i) |
| spreadsheet | — | 21 (i) | 32 (i) | 18 | ~26 (i) | ~24 (i) | ~34 (i) | ~23 (i) | — | — | — | — | — | — | — | — | 40 (i) | — | — | 26 (i) | — | — |

## Task: csv-bugfix

Starter baseline (no changes made): 11/19 — combos at or below this accomplished nothing.

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| solo-dsv4* | 1/4 | 25/25 | 100% | 127.2 | 25 | 377117 | model_substituted, read_hidden |
| plansolo* | 1/3 | 25/25 | 100% | 281.6 | 21 | 285050 | model_substituted, read_hidden, timeout_p1 |
| planbuild-p_coder-b_qwen36* | 1/3 | 19/19 | 100% | 260.5 | 26 | 923357 | model_substituted, read_hidden |
| planbuild-p_coder-b_glm47* | 1/3 | 19/19 | 100% | 272.8 | 15 | 353524 | model_substituted |
| planbuild-p_coder-b_dsv4* | 1/3 | 19/19 | 100% | 360.4 | 33 | 1017977 | model_substituted |
| planbuild-p_coder-b_coder* | 1/3 | 19/19 | 100% | 238.1 | 35 | 1233806 | model_substituted |
| planbuild-dsv4 | 3/4 | 25/25 | 100% | 677.7 | 12 | 201779 | read_hidden, timeout_p1 |
| planbuild-ds4-coder* | 1/4 | 25/25 | 100% | 236.0 | 42 | 1263317 | exit_1_p1, exit_1_p2, model_substituted, provider_error_p1, provider_error_p2, read_hidden |
| planbuild* | 1/3 | 25/25 | 100% | 127.7 | 13 | 201846 | budget_exhausted_p1, exit_1_p1, model_substituted, read_hidden |

## Task: deepswe-true-myth-iterable-collection-combinators

Validation: oracle reward 1, untouched repo F2P 0/96 (P2P 561/561).

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| pi-ds | 1/1 | 1/1 | 100% | 2179.2 | 65 | 5893200 | — |

## Task: minilang

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| planbuild-p_qwen35-b_qwen36* | 1/3 | 50/50 | 100% | 135.7 | 13 | 410322 | model_substituted, read_hidden |
| planbuild-p_qwen35-b_glm47* | 1/3 | 50/50 | 100% | 237.1 | 44 | 2209050 | model_substituted, read_hidden |
| planbuild-p_qwen35-b_dsv4* | 1/3 | 50/50 | 100% | 279.2 | 16 | 605483 | model_substituted, read_hidden |
| planbuild-p_qwen35-b_coder* | 1/3 | 50/50 | 100% | 267.8 | 38 | 1869629 | model_substituted, read_hidden |
| planbuild-p_mistral-b_qwen36* | 1/3 | 50/50 | 100% | 145.1 | 19 | 622418 | model_substituted, read_hidden |
| planbuild-p_mistral-b_glm47* | 1/3 | 50/50 | 100% | 299.7 | 17 | 766840 | model_substituted, read_hidden |
| planbuild-p_mistral-b_dsv4* | 1/3 | 50/50 | 100% | 439.5 | 50 | 2144147 | model_substituted, read_hidden |
| planbuild-p_mistral-b_coder* | 1/3 | 50/50 | 100% | 144.2 | 17 | 570575 | model_substituted, read_hidden |
| planbuild-p_coder-b_qwen36* | 1/3 | 50/50 | 100% | 793.7 | 75 | 3896890 | model_substituted |
| planbuild-p_coder-b_glm47* | 1/3 | 50/50 | 100% | 569.6 | 56 | 2458078 | model_substituted, read_hidden |
| planbuild-p_coder-b_dsv4* | 1/3 | 50/50 | 100% | 215.2 | 27 | 1059489 | model_substituted |
| planbuild-p_coder-b_coder* | 1/3 | 50/50 | 100% | 649.7 | 78 | 3497598 | model_substituted, read_hidden |
| planbuild-dsv4* | 1/3 | 50/50 | 100% | 284.6 | 18 | 668622 | read_hidden |
| planbuild-ds4-coder* | 1/3 | 50/50 | 100% | 239.4 | 21 | 881267 | model_substituted, read_hidden |
| planbuild* | 1/3 | 50/50 | 100% | 167.8 | 18 | 695577 | model_substituted, read_hidden |

## Task: minilang2

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| solo-qwen36* | 1/8 | 200/200 | 100% | 592.1 | 52 | 3168357 | budget_exhausted_p1, contaminated_hidden_tests, exit_1_p1, model_substituted, timeout_p1 |
| solo-qwen35* | 1/3 | 200/200 | 100% | 1316.9 | 25 | 1371876 | contaminated_hidden_tests, model_substituted, stalled_p1 |
| solo-dsv4* | 1/3 | 200/200 | 100% | 1800.2 | 120 | 14113736 | contaminated_hidden_tests, model_substituted, timeout_p1 |
| solo-coder* | 1/1 | 200/200 | 100% | 558.1 | 125 | 6902124 | contaminated_hidden_tests |
| solo* | 1/6 | 200/200 | 100% | 1022.6 | 162 | 13755642 | agent_fallback_p1, contaminated_hidden_tests, expected_agent_missing_in_db, read_hidden |
| planbuild-p_qwen35-b_qwen36* | 1/3 | 200/200 | 100% | 280.7 | 14 | 754323 | model_substituted, read_hidden |
| planbuild-p_qwen35-b_coder* | 1/3 | 200/200 | 100% | 387.8 | 22 | 1344205 | model_substituted, read_hidden |
| planbuild-p_coder-b_qwen36* | 1/3 | 200/200 | 100% | 318.1 | 24 | 1288137 | model_substituted, read_hidden |
| planbuild-p_coder-b_glm47* | 1/3 | 200/200 | 100% | 659.1 | 17 | 991385 | model_substituted, read_hidden, stalled_p2 |
| planbuild-p_coder-b_coder* | 1/3 | 200/200 | 100% | 304.2 | 22 | 1216207 | model_substituted, read_hidden |
| planbuild-ds4-coder* | 1/6 | 200/200 | 100% | 292.1 | 27 | 1812370 | contaminated_hidden_tests, model_substituted, read_hidden |
| planbuild-p_qwen35-b_glm47* | 1/3 | 198/200 | 99% | 987.0 | 91 | 6192519 | model_substituted, read_hidden |
| planbuild-p_mistral-b_dsv4* | 1/3 | 198/200 | 99% | 1060.5 | 143 | 12853667 | model_substituted, read_hidden |
| planbuild* | 1/3 | 198/200 | 99% | 931.1 | 128 | 10329501 | model_substituted, read_hidden, stalled_p2 |
| planbuild-p_mistral-b_qwen36* | 1/3 | 197/200 | 98% | 1394.5 | 112 | 8888943 | model_substituted, read_hidden |
| planbuild-p_mistral-b_glm47* | 1/3 | 197/200 | 98% | 811.4 | 116 | 7859731 | model_substituted, read_hidden |
| planbuild-dsv4 | 1/3 | 197/200 | 98% | 1581.3 | 145 | 11485809 | read_hidden |
| planbuild-p_qwen35-b_dsv4* | 1/3 | 195/200 | 98% | 687.0 | 81 | 5262439 | model_substituted, read_hidden |
| planbuild-p_coder-b_dsv4* | 1/3 | 195/200 | 98% | 1114.0 | 118 | 9070542 | model_substituted |
| planbuild-p_mistral-b_coder* | 1/3 | 0/200 | 0% | 178.2 | 23 | 1446722 | model_substituted, read_hidden, stalled_p2 |

## Task: spreadsheet

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| planbuild-p_coder-b_qwen36* | 1/5 | 21/21 | 100% | 349.4 | 23 | 624988 | budget_exhausted_p2, exit_1_p2, model_substituted, read_hidden |
| planbuild-p_coder-b_glm47* | 1/6 | 21/21 | 100% | 295.6 | 34 | 1879632 | model_substituted |
| planbuild-p_coder-b_dsv4* | 1/3 | 21/21 | 100% | 182.1 | 24 | 593655 | model_substituted, read_hidden |
| planbuild-p_coder-b_coder* | 1/5 | 21/21 | 100% | 146.0 | 26 | 719121 | budget_exhausted_p2, exit_1_p2, model_substituted, read_hidden |
| planbuild-ds4-coder* | 1/3 | 34/34 | 100% | 336.0 | 28 | 846253 | model_substituted, read_hidden |
| planbuild* | 1/3 | 34/34 | 100% | 356.5 | 20 | 517964 | model_substituted |
| planbuild-dsv4 | 3/6 | 33/34 | 97% | 444.2 | 20 | 515222 | budget_exhausted_p2, exit_1_p1, exit_1_p2, provider_error_p1, read_hidden |
| solo-dsv4* | 1/5 | 32/34 | 94% | 485.2 | 25 | 1296131 | model_substituted, stalled_p1 |
| plansolo* | 1/3 | 31/34 | 91% | 272.6 | 39 | 1258474 | model_substituted, read_hidden |

## Overall ranking

Mean of per-task median pass rates (only over tasks the combo ran).

| rank | combo | mean pass rate | tasks covered |
|---|---|---|---|
| 1 | solo-qwen36 | 100% | 1/5 |
| 2 | solo-qwen35 | 100% | 1/5 |
| 3 | solo-coder | 100% | 1/5 |
| 4 | solo | 100% | 1/5 |
| 5 | planbuild-p_qwen35-b_qwen36 | 100% | 2/5 |
| 6 | planbuild-p_qwen35-b_coder | 100% | 2/5 |
| 7 | planbuild-p_coder-b_qwen36 | 100% | 4/5 |
| 8 | planbuild-p_coder-b_glm47 | 100% | 4/5 |
| 9 | planbuild-p_coder-b_coder | 100% | 4/5 |
| 10 | planbuild-ds4-coder | 100% | 4/5 |
| 11 | pi-ds | 100% | 1/5 |
| 12 | planbuild | 100% | 4/5 |
| 13 | planbuild-p_qwen35-b_glm47 | 100% | 2/5 |
| 14 | planbuild-p_mistral-b_dsv4 | 100% | 2/5 |
| 15 | planbuild-p_coder-b_dsv4 | 99% | 4/5 |
| 16 | planbuild-p_mistral-b_qwen36 | 99% | 2/5 |
| 17 | planbuild-p_mistral-b_glm47 | 99% | 2/5 |
| 18 | planbuild-dsv4 | 99% | 4/5 |
| 19 | planbuild-p_qwen35-b_dsv4 | 99% | 2/5 |
| 20 | solo-dsv4 | 98% | 3/5 |
| 21 | plansolo | 96% | 2/5 |
| 22 | planbuild-p_mistral-b_coder | 50% | 2/5 |
