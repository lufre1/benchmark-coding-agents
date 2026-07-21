# Testbench report

Generated 2026-07-21T07:03:41+00:00 from 163 run(s). Raw data: `results.csv`, `runs/*/result.json`.

`*` = every run of this cell was interrupted (provider outage/stall); the best attempt is shown as a lower bound.

## API requests per task × combo

Median SAIA requests actually charged per run (budget-counter delta, includes failed/5xx requests). `~N` = LLM-response count fallback when no budget snapshot bracketed the run; `(i)` = interrupted lower-bound cell.

| task | planbuild | planbuild-ds4-coder | planbuild-dsv4 | planbuild-p_coder-b_coder | planbuild-p_coder-b_dsv4 | planbuild-p_coder-b_glm47 | planbuild-p_coder-b_qwen36 | planbuild-p_mistral-b_coder | planbuild-p_mistral-b_dsv4 | planbuild-p_mistral-b_glm47 | planbuild-p_mistral-b_qwen36 | planbuild-p_qwen35-b_coder | planbuild-p_qwen35-b_dsv4 | planbuild-p_qwen35-b_glm47 | planbuild-p_qwen35-b_qwen36 | plansolo | solo-coder | solo-dsv4 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| csv-bugfix | 59 | 34 | 98 | ~22 | ~27 | ~16 | ~31 | — | — | — | — | — | — | — | — | 20 | — | 26 |
| minilang | 16 | 56 | 19 | 11 | 34 | 38 | 61 | 18 | 9 | 11 | 11 | 37 | 17 | 62 | 21 | — | — | — |
| minilang2 | 74 | 16 | 26 | 51 | 97 | 12 | 23 | 20 | 122 | 45 | 19 | 23 | 22 | 18 | 19 | — | 131 | — |
| spreadsheet | 22 | 32 | 21 | ~34 | ~24 | ~28 | ~25 | — | — | — | — | — | — | — | — | 29 | — | 26 |

## Task: csv-bugfix

Starter baseline (no changes made): 19/19 — combos at or below this accomplished nothing.

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| solo-dsv4 | 4/4 | 25.0/25 | 100% | 136.8 | 25.0 | 428268 | — |
| plansolo | 3/3 | 25/25 | 100% | 492.6 | 17 | 217847 | timeout_p1 |
| planbuild-p_coder-b_qwen36 | 3/3 | 19/19 | 100% | 260.5 | 31 | 923357 | — |
| planbuild-p_coder-b_glm47 | 3/3 | 19/19 | 100% | 302.1 | 16 | 443896 | — |
| planbuild-p_coder-b_dsv4 | 3/3 | 19/19 | 100% | 360.4 | 27 | 1017977 | — |
| planbuild-p_coder-b_coder | 3/3 | 19/19 | 100% | 250.2 | 22 | 592938 | — |
| planbuild-dsv4 | 4/4 | 25.0/25 | 100% | 788.9 | 13.0 | 212790 | timeout_p1 |
| planbuild-ds4-coder | 2/4 | 25.0/25 | 100% | 219.6 | 32.5 | 913991 | exit_1_p1, exit_1_p2, provider_error_p1, provider_error_p2 |
| planbuild | 2/3 | 25.0/25 | 100% | 288.3 | 22.5 | 585641 | budget_exhausted_p1, exit_1_p1 |

## Task: minilang

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| planbuild-p_qwen35-b_qwen36 | 3/3 | 50/50 | 100% | 147.2 | 21 | 783355 | — |
| planbuild-p_qwen35-b_coder | 3/3 | 50/50 | 100% | 267.8 | 36 | 1433680 | — |
| planbuild-p_mistral-b_qwen36 | 3/3 | 50/50 | 100% | 127.2 | 16 | 480169 | — |
| planbuild-p_coder-b_dsv4 | 3/3 | 50/50 | 100% | 215.2 | 35 | 1240893 | — |
| planbuild-p_coder-b_coder | 3/3 | 50/50 | 100% | 147.6 | 12 | 312612 | — |
| planbuild-dsv4 | 3/3 | 50/50 | 100% | 279.2 | 18 | 624905 | — |
| planbuild | 3/3 | 50/50 | 100% | 282.7 | 18 | 695577 | — |
| planbuild-p_qwen35-b_glm47 | 3/3 | 49/50 | 98% | 354.9 | 61 | 2741831 | — |
| planbuild-p_mistral-b_glm47 | 3/3 | 49/50 | 98% | 299.7 | 17 | 766840 | — |
| planbuild-p_mistral-b_coder | 3/3 | 49/50 | 98% | 167.7 | 17 | 570575 | — |
| planbuild-p_coder-b_qwen36 | 3/3 | 49/50 | 98% | 347.7 | 51 | 2223550 | — |
| planbuild-p_coder-b_glm47 | 3/3 | 49/50 | 98% | 528.0 | 40 | 1936214 | — |
| planbuild-ds4-coder | 3/3 | 49/50 | 98% | 466.9 | 55 | 2384215 | — |
| planbuild-p_qwen35-b_dsv4 | 3/3 | 48/50 | 96% | 279.2 | 16 | 605483 | — |
| planbuild-p_mistral-b_dsv4 | 3/3 | 0/50 | 0% | 163.5 | 8 | 257188 | — |

## Task: minilang2

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| solo-coder | 1/1 | 200/200 | 100% | 558.1 | 125 | 6902124 | — |
| planbuild-p_coder-b_coder | 3/3 | 199/200 | 100% | 714.8 | 52 | 4649048 | — |
| planbuild-p_mistral-b_dsv4 | 3/3 | 198/200 | 99% | 1060.5 | 121 | 9145061 | — |
| planbuild-p_coder-b_qwen36 | 3/3 | 198/200 | 99% | 662.7 | 79 | 5579578 | — |
| planbuild-p_qwen35-b_qwen36 | 3/3 | 197/200 | 98% | 280.7 | 18 | 1260115 | — |
| planbuild-dsv4 | 3/3 | 197/200 | 98% | 456.5 | 31 | 2456209 | — |
| planbuild-p_qwen35-b_coder | 3/3 | 194/200 | 97% | 387.8 | 22 | 1344205 | — |
| planbuild-p_coder-b_dsv4 | 3/3 | 193/200 | 96% | 1153.2 | 96 | 8778877 | — |
| planbuild-ds4-coder | 6/6 | 100.0/200 | 50% | 75.7 | 15.5 | 905628 | — |
| planbuild | 2/3 | 99.0/200 | 50% | 719.3 | 73.5 | 5856567 | stalled_p2 |
| planbuild-p_qwen35-b_glm47 | 3/3 | 0/200 | 0% | 113.2 | 17 | 858261 | — |
| planbuild-p_qwen35-b_dsv4 | 3/3 | 0/200 | 0% | 117.6 | 21 | 1044761 | — |
| planbuild-p_mistral-b_qwen36 | 3/3 | 0/200 | 0% | 123.2 | 18 | 1163057 | — |
| planbuild-p_mistral-b_glm47 | 3/3 | 0/200 | 0% | 273.6 | 44 | 3111248 | — |
| planbuild-p_mistral-b_coder | 2/3 | 0.0/200 | 0% | 130.1 | 19.0 | 1164545 | stalled_p2 |
| planbuild-p_coder-b_glm47 | 2/3 | 0.0/200 | 0% | 446.6 | 20.0 | 1458334 | stalled_p2 |

## Task: spreadsheet

| combo | runs | hidden tests (median) | pass rate | wall s | requests | tokens | flags |
|---|---|---|---|---|---|---|---|
| planbuild-p_coder-b_qwen36 | 3/5 | 21/21 | 100% | 255.3 | 25 | 864821 | budget_exhausted_p2, exit_1_p2 |
| planbuild-p_coder-b_glm47 | 6/6 | 21.0/21 | 100% | 222.1 | 28.0 | 1040288 | — |
| planbuild-p_coder-b_dsv4 | 3/3 | 21/21 | 100% | 182.1 | 24 | 593655 | — |
| planbuild-ds4-coder | 3/3 | 34/34 | 100% | 260.4 | 28 | 846253 | — |
| planbuild | 3/3 | 34/34 | 100% | 356.5 | 25 | 663739 | — |
| planbuild-dsv4 | 4/6 | 33.5/34 | 99% | 444.5 | 20.0 | 618020 | budget_exhausted_p2, exit_1_p1, exit_1_p2, provider_error_p1 |
| planbuild-p_coder-b_coder | 3/5 | 20/21 | 95% | 334.1 | 34 | 1733135 | budget_exhausted_p2, exit_1_p2 |
| plansolo | 3/3 | 30/34 | 88% | 231.7 | 28 | 887141 | — |
| solo-dsv4 | 4/5 | 24.5/34 | 72% | 392.4 | 25.0 | 1079429 | stalled_p1 |

## Overall ranking

Mean of per-task median pass rates (only over tasks the combo ran).

| rank | combo | mean pass rate | tasks covered |
|---|---|---|---|
| 1 | solo-coder | 100% | 1/4 |
| 2 | planbuild-dsv4 | 99% | 4/4 |
| 3 | planbuild-p_qwen35-b_qwen36 | 99% | 2/4 |
| 4 | planbuild-p_coder-b_qwen36 | 99% | 4/4 |
| 5 | planbuild-p_coder-b_dsv4 | 99% | 4/4 |
| 6 | planbuild-p_coder-b_coder | 99% | 4/4 |
| 7 | planbuild-p_qwen35-b_coder | 98% | 2/4 |
| 8 | plansolo | 94% | 2/4 |
| 9 | planbuild | 87% | 4/4 |
| 10 | planbuild-ds4-coder | 87% | 4/4 |
| 11 | solo-dsv4 | 86% | 2/4 |
| 12 | planbuild-p_coder-b_glm47 | 74% | 4/4 |
| 13 | planbuild-p_mistral-b_qwen36 | 50% | 2/4 |
| 14 | planbuild-p_mistral-b_dsv4 | 50% | 2/4 |
| 15 | planbuild-p_qwen35-b_glm47 | 49% | 2/4 |
| 16 | planbuild-p_mistral-b_glm47 | 49% | 2/4 |
| 17 | planbuild-p_mistral-b_coder | 49% | 2/4 |
| 18 | planbuild-p_qwen35-b_dsv4 | 48% | 2/4 |
