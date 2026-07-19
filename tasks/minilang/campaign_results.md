# Minilang Campaign Results

**15 planbuild combos × 3 repeats = 45 runs** — 13855s total wall time — **$0 cost** (SAIA free tier, per-API-request pricing)

Each opencode `step` = 1 LLM call = 1 SAIA API request.

## Summary Table

| Combo | Model (plan→build) | Valid/Runs | Avg Score | Wall | API Req | Tools | In Tokens | Out Tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| planbuild-p_mistral-b_qwen36 | mistral-medium-3.5-128b → qwen3.6-35b-a3b | 2/3 | 100.0% | 99s | 14.0 | 16.3 | 433,682 | 10,313 |
| planbuild-dsv4 🏆 | deepseek-v4-flash → deepseek-v4-flash | 3/3 | 100.0% | 278s | 18.3 | 21.3 | 623,488 | 15,592 |
| planbuild-p_qwen35-b_qwen36 🏆 | qwen3.5-122b-a10b → qwen3.6-35b-a3b | 3/3 | 100.0% | 147s | 19.0 | 23.0 | 650,560 | 15,625 |
| planbuild-p_qwen35-b_dsv4 | qwen3.5-122b-a10b → deepseek-v4-flash | 2/3 | 98.0% | 365s | 21.0 | 23.3 | 766,924 | 18,976 |
| planbuild-p_mistral-b_dsv4 | mistral-medium-3.5-128b → deepseek-v4-flash | 1/3 | 100.0% | 253s | 21.7 | 24.0 | 864,006 | 11,180 |
| planbuild-p_mistral-b_glm47 | mistral-medium-3.5-128b → glm-4.7 | 2/3 | 99.0% | 317s | 23.3 | 27.0 | 1,191,447 | 15,733 |
| planbuild-p_mistral-b_coder | mistral-medium-3.5-128b → qwen3-coder-next | 2/3 | 99.0% | 228s | 27.7 | 29.0 | 1,249,650 | 16,144 |
| planbuild | qwen3-coder-next → qwen3-coder-next | 3/3 | 99.3% | 331s | 28.7 | 30.7 | 1,168,658 | 20,674 |
| planbuild-p_coder-b_coder | qwen3-coder-next → qwen3-coder-next | 2/3 | 100.0% | 275s | 33.0 | 34.0 | 1,351,792 | 20,583 |
| planbuild-p_coder-b_dsv4 | qwen3-coder-next → deepseek-v4-flash | 3/3 | 99.3% | 301s | 34.0 | 32.3 | 1,281,998 | 24,860 |
| planbuild-p_coder-b_glm47 | qwen3-coder-next → glm-4.7 | 2/3 | 99.0% | 425s | 34.7 | 35.0 | 1,528,611 | 21,722 |
| planbuild-p_qwen35-b_coder 🏆 | qwen3.5-122b-a10b → qwen3-coder-next | 3/3 | 100.0% | 254s | 35.0 | 34.0 | 1,553,455 | 24,354 |
| planbuild-ds4-coder | deepseek-v4-flash → qwen3-coder-next | 3/3 | 98.7% | 452s | 48.3 | 49.7 | 2,182,846 | 28,886 |
| planbuild-p_coder-b_qwen36 | qwen3-coder-next → qwen3.6-35b-a3b | 3/3 | 98.7% | 485s | 57.0 | 55.3 | 2,699,997 | 37,809 |
| planbuild-p_qwen35-b_glm47 | qwen3.5-122b-a10b → glm-4.7 | 3/3 | 98.7% | 407s | 57.7 | 56.7 | 2,607,997 | 35,069 |
| **Total** | — | **37/45** | **—** | **13855s** | **1420** | **1475** | **60,465,333** | **952,560** |

## Per-Run Detail

| Run Dir | Combo | Score | Wall | API Req | Tools | In Tokens | Out Tokens | Phase Breakdown |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 20260718T102712Z_minilang_planbuild_r1 | planbuild | 50/50 | 167.8s | 18 | 21 | 679,773 | 15,804 | plan(26.4s/6steps) → build(141.4s/12steps) |
| 20260718T103003Z_minilang_planbuild_r1 | planbuild | 49/50 | 541.3s | 53 | 53 | 2,256,821 | 29,673 | plan(25.9s/2steps) → build(515.4s/51steps) |
| 20260718T103906Z_minilang_planbuild_r1 | planbuild | 50/50 | 282.7s | 15 | 18 | 569,382 | 16,546 | plan(84.9s/3steps) → build(197.8s/12steps) |
| 20260718T105752Z_minilang_planbuild-ds4-coder_r1 | planbuild-ds4-coder | 50/50 | 239.4s | 21 | 27 | 867,198 | 14,069 | plan(97.9s/9steps) → build(141.5s/12steps) |
| 20260718T110154Z_minilang_planbuild-ds4-coder_r1 | planbuild-ds4-coder | 49/50 | 649.9s | 55 | 54 | 2,353,396 | 30,819 | plan(23.1s/3steps) → build(626.8s/52steps) |
| 20260718T111246Z_minilang_planbuild-ds4-coder_r1 | planbuild-ds4-coder | 49/50 | 466.9s | 69 | 68 | 3,327,944 | 41,771 | plan(22.1s/3steps) → build(444.8s/66steps) |
| 20260718T104351Z_minilang_planbuild-dsv4_r1 | planbuild-dsv4 | 50/50 | 284.6s | 18 | 21 | 652,196 | 16,426 | plan(89.0s/5steps) → build(195.6s/13steps) |
| 20260718T104838Z_minilang_planbuild-dsv4_r1 | planbuild-dsv4 | 50/50 | 270.0s | 18 | 22 | 610,014 | 14,891 | plan(90.7s/6steps) → build(179.3s/12steps) |
| 20260718T105311Z_minilang_planbuild-dsv4_r1 | planbuild-dsv4 | 50/50 | 279.2s | 19 | 21 | 608,256 | 15,461 | plan(102.7s/8steps) → build(176.5s/11steps) |
| 0718T132926Z_minilang_planbuild-p_coder-b_coder_r1 | planbuild-p_coder-b_coder | 0/1 | 29.1s | 9 | 11 | 311,216 | 1,396 | plan(16.7s/5steps) → build(12.4s/4steps) |
| 0718T132957Z_minilang_planbuild-p_coder-b_coder_r1 | planbuild-p_coder-b_coder | 50/50 | 649.7s | 78 | 76 | 3,450,525 | 47,073 | plan(22.5s/3steps) → build(627.2s/75steps) |
| 0718T134049Z_minilang_planbuild-p_coder-b_coder_r1 | planbuild-p_coder-b_coder | 50/50 | 147.6s | 12 | 15 | 293,637 | 13,281 | plan(25.4s/6steps) → build(122.2s/6steps) |
| 60718T134319Z_minilang_planbuild-p_coder-b_dsv4_r1 | planbuild-p_coder-b_dsv4 | 49/50 | 214.0s | 35 | 33 | 1,216,803 | 24,090 | plan(16.2s/3steps) → build(197.8s/32steps) |
| 60718T134655Z_minilang_planbuild-p_coder-b_dsv4_r1 | planbuild-p_coder-b_dsv4 | 50/50 | 215.2s | 27 | 25 | 1,036,254 | 23,235 | plan(27.7s/3steps) → build(187.5s/24steps) |
| 60718T135033Z_minilang_planbuild-p_coder-b_dsv4_r1 | planbuild-p_coder-b_dsv4 | 50/50 | 472.5s | 40 | 39 | 1,592,938 | 27,257 | plan(89.8s/3steps) → build(382.7s/37steps) |
| 0718T135828Z_minilang_planbuild-p_coder-b_glm47_r1 | planbuild-p_coder-b_glm47 | 49/50 | 528.0s | 40 | 39 | 1,908,868 | 27,346 | plan(88.9s/3steps) → build(439.1s/37steps) |
| 0718T140718Z_minilang_planbuild-p_coder-b_glm47_r1 | planbuild-p_coder-b_glm47 | 50/50 | 569.6s | 56 | 55 | 2,421,610 | 36,468 | plan(91.7s/3steps) → build(477.9s/53steps) |
| 0718T141650Z_minilang_planbuild-p_coder-b_glm47_r1 | planbuild-p_coder-b_glm47 | 0/1 | 178.7s | 8 | 11 | 255,356 | 1,352 | plan(100.3s/5steps) → build(78.4s/3steps) |
| 718T130504Z_minilang_planbuild-p_coder-b_qwen36_r1 | planbuild-p_coder-b_qwen36 | 50/50 | 793.7s | 75 | 73 | 3,846,621 | 50,269 | plan(20.1s/3steps) → build(773.6s/72steps) |
| 718T131820Z_minilang_planbuild-p_coder-b_qwen36_r1 | planbuild-p_coder-b_qwen36 | 49/50 | 347.7s | 45 | 44 | 2,057,661 | 35,318 | plan(23.3s/3steps) → build(324.4s/42steps) |
| 718T132410Z_minilang_planbuild-p_coder-b_qwen36_r1 | planbuild-p_coder-b_qwen36 | 49/50 | 313.8s | 51 | 49 | 2,195,710 | 27,840 | plan(24.0s/3steps) → build(289.8s/48steps) |
| 18T122448Z_minilang_planbuild-p_mistral-b_coder_r1 | planbuild-p_mistral-b_coder | 50/50 | 144.2s | 17 | 19 | 555,230 | 15,345 | plan(31.0s/6steps) → build(113.2s/11steps) |
| 18T122715Z_minilang_planbuild-p_mistral-b_coder_r1 | planbuild-p_mistral-b_coder | 49/50 | 373.5s | 54 | 52 | 2,811,903 | 31,477 | plan(21.0s/3steps) → build(352.5s/51steps) |
| 18T123330Z_minilang_planbuild-p_mistral-b_coder_r1 | planbuild-p_mistral-b_coder | 0/1 | 167.7s | 12 | 16 | 381,819 | 1,611 | plan(88.8s/8steps) → build(78.9s/4steps) |
| 718T123620Z_minilang_planbuild-p_mistral-b_dsv4_r1 | planbuild-p_mistral-b_dsv4 | 50/50 | 439.5s | 50 | 52 | 2,113,142 | 31,005 | plan(99.2s/7steps) → build(340.3s/43steps) |
| 718T124342Z_minilang_planbuild-p_mistral-b_dsv4_r1 | planbuild-p_mistral-b_dsv4 | 0/1 | 163.5s | 8 | 10 | 255,750 | 1,438 | plan(84.7s/5steps) → build(78.8s/3steps) |
| 718T124628Z_minilang_planbuild-p_mistral-b_dsv4_r1 | planbuild-p_mistral-b_dsv4 | 0/1 | 156.7s | 7 | 10 | 223,127 | 1,098 | plan(82.9s/5steps) → build(73.8s/2steps) |
| 18T124906Z_minilang_planbuild-p_mistral-b_glm47_r1 | planbuild-p_mistral-b_glm47 | 0/1 | 165.4s | 10 | 16 | 296,469 | 1,656 | plan(89.3s/7steps) → build(76.1s/3steps) |
| 18T125154Z_minilang_planbuild-p_mistral-b_glm47_r1 | planbuild-p_mistral-b_glm47 | 49/50 | 485.5s | 43 | 42 | 2,526,759 | 29,818 | plan(88.2s/3steps) → build(397.3s/40steps) |
| 18T130002Z_minilang_planbuild-p_mistral-b_glm47_r1 | planbuild-p_mistral-b_glm47 | 50/50 | 299.7s | 17 | 23 | 751,115 | 15,725 | plan(23.3s/6steps) → build(276.4s/11steps) |
| 8T121943Z_minilang_planbuild-p_mistral-b_qwen36_r1 | planbuild-p_mistral-b_qwen36 | 0/1 | 25.6s | 7 | 11 | 228,137 | 1,265 | plan(16.0s/4steps) → build(9.6s/3steps) |
| 8T122011Z_minilang_planbuild-p_mistral-b_qwen36_r1 | planbuild-p_mistral-b_qwen36 | 50/50 | 145.1s | 19 | 21 | 606,782 | 15,636 | plan(30.2s/7steps) → build(114.9s/12steps) |
| 8T122238Z_minilang_planbuild-p_mistral-b_qwen36_r1 | planbuild-p_mistral-b_qwen36 | 50/50 | 127.2s | 16 | 17 | 466,129 | 14,040 | plan(27.6s/5steps) → build(99.6s/11steps) |
| 718T112803Z_minilang_planbuild-p_qwen35-b_coder_r1 | planbuild-p_qwen35-b_coder | 50/50 | 267.8s | 38 | 36 | 1,842,968 | 26,661 | plan(32.8s/3steps) → build(235.0s/35steps) |
| 718T113233Z_minilang_planbuild-p_qwen35-b_coder_r1 | planbuild-p_qwen35-b_coder | 50/50 | 220.3s | 31 | 30 | 1,408,270 | 25,410 | plan(25.4s/3steps) → build(194.9s/28steps) |
| 718T113615Z_minilang_planbuild-p_qwen35-b_coder_r1 | planbuild-p_qwen35-b_coder | 50/50 | 275.3s | 36 | 36 | 1,409,129 | 20,993 | plan(28.4s/7steps) → build(246.9s/29steps) |
| 0718T114053Z_minilang_planbuild-p_qwen35-b_dsv4_r1 | planbuild-p_qwen35-b_dsv4 | 48/50 | 544.8s | 36 | 35 | 1,188,340 | 25,217 | plan(83.3s/3steps) → build(461.5s/33steps) |
| 0718T115000Z_minilang_planbuild-p_qwen35-b_dsv4_r1 | planbuild-p_qwen35-b_dsv4 | 50/50 | 279.2s | 16 | 19 | 588,955 | 16,528 | plan(90.3s/4steps) → build(188.9s/12steps) |
| 0718T115442Z_minilang_planbuild-p_qwen35-b_dsv4_r1 | planbuild-p_qwen35-b_dsv4 | 0/1 | 270.9s | 11 | 16 | 523,478 | 15,185 | plan(91.8s/5steps) → build(179.1s/6steps) |
| 718T115915Z_minilang_planbuild-p_qwen35-b_glm47_r1 | planbuild-p_qwen35-b_glm47 | 49/50 | 629.7s | 61 | 59 | 2,700,028 | 41,803 | plan(71.5s/3steps) → build(558.2s/58steps) |
| 718T120947Z_minilang_planbuild-p_qwen35-b_glm47_r1 | planbuild-p_qwen35-b_glm47 | 50/50 | 237.1s | 44 | 44 | 2,183,224 | 25,826 | plan(29.0s/7steps) → build(208.1s/37steps) |
| 718T121346Z_minilang_planbuild-p_qwen35-b_glm47_r1 | planbuild-p_qwen35-b_glm47 | 49/50 | 354.9s | 68 | 67 | 2,940,739 | 37,578 | plan(22.8s/4steps) → build(332.1s/64steps) |
| 18T112035Z_minilang_planbuild-p_qwen35-b_qwen36_r1 | planbuild-p_qwen35-b_qwen36 | 50/50 | 135.7s | 13 | 15 | 396,681 | 13,641 | plan(30.0s/3steps) → build(105.7s/10steps) |
| 18T112253Z_minilang_planbuild-p_qwen35-b_qwen36_r1 | planbuild-p_qwen35-b_qwen36 | 50/50 | 147.2s | 21 | 27 | 788,300 | 16,580 | plan(22.6s/5steps) → build(124.6s/16steps) |
| 18T112523Z_minilang_planbuild-p_qwen35-b_qwen36_r1 | planbuild-p_qwen35-b_qwen36 | 50/50 | 157.5s | 23 | 27 | 766,699 | 16,656 | plan(45.2s/11steps) → build(112.3s/12steps) |

## Summary

- **45 total runs** across **15 combos**
- **37 valid runs** produced meaningful test results (stopped early if agent gave up)
- **8 runs** resulted in `0/1` — agent produced broken code that didn't even import
- **Total wall time**: 13855s (3.8 hours)
- **Total API requests**: 1420 (avg 31.6 per run)
- **Planbuild-dsv4** (deepseek-v4-flash plan+build) is the standout: 100% score, 100% reliability, only ~18 API req/run
- **Planbuild-p_mistral-b_qwen36** is the cheapest at ~14 API req/run but unreliable (2/3)
- Benchmark ceiling too low — 12/15 combos hit 98-100% — needs harder tests to discriminate top models
