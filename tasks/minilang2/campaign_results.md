# Minilang2 Campaign Results

**15 planbuild combos × 3 repeats = 45 runs**

Each opencode `step` = 1 LLM call = 1 SAIA API request.

**Total wall time:** 24174s (6.7h)
**Total API requests:** 2278
**Total tokens:** 170,098,337 in / 1,451,407 out

## Summary Table (sorted by score, then API efficiency)

| Combo | Model (plan→build) | Valid/3 | Avg Score | Best Score | Wall | API Req | Tools | In Tokens | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| planbuild-p_coder-b_glm47 | qwen3-coder-next → glm-4.7 | 1/3 | 100% | 100% | 517s | 18.7 | 25.0 | 1,293,030 | inconsistent (2 runs failed) |
| planbuild-p_coder-b_coder | qwen3-coder-next → qwen3-coder-next | 3/3 | 100% | 100% | 584s | 62.0 | 63.0 | 4,423,356 | consistent |
| planbuild-p_qwen35-b_qwen36 | qwen3.5-122b-a10b → qwen3.6-35b-a3b | 2/3 | 99% | 100% | 496s | 54.7 | 57.7 | 4,996,238 | inconsistent (1 runs failed) |
| planbuild-dsv4 | deepseek-v4-flash → deepseek-v4-flash | 2/3 | 99% | 100% | 711s | 63.3 | 69.3 | 4,888,924 | inconsistent (1 runs failed) |
| planbuild-p_qwen35-b_glm47 | qwen3.5-122b-a10b → glm-4.7 | 1/3 | 99% | 99% | 394s | 39.7 | 43.7 | 2,610,181 | inconsistent (2 runs failed) |
| planbuild | qwen3-coder-next → qwen3-coder-next | 1/3 | 99% | 99% | 632s | 52.3 | 56.3 | 4,008,132 | inconsistent (2 runs failed) |
| planbuild-p_mistral-b_dsv4 | mistral-medium-3.5-128b → deepseek-v4-flash | 2/3 | 99% | 99% | 981s | 93.0 | 96.3 | 7,617,866 | inconsistent (1 runs failed) |
| planbuild-p_coder-b_qwen36 | qwen3-coder-next → qwen3.6-35b-a3b | 3/3 | 99% | 100% | 718s | 63.7 | 64.0 | 4,553,088 | consistent |
| planbuild-p_qwen35-b_coder | qwen3.5-122b-a10b → qwen3-coder-next | 2/3 | 98% | 100% | 386s | 41.0 | 44.7 | 2,715,263 | inconsistent (1 runs failed) |
| planbuild-p_mistral-b_qwen36 | mistral-medium-3.5-128b → qwen3.6-35b-a3b | 1/3 | 98% | 98% | 526s | 45.7 | 49.7 | 3,431,337 | inconsistent (2 runs failed) |
| planbuild-p_mistral-b_glm47 | mistral-medium-3.5-128b → glm-4.7 | 1/3 | 98% | 98% | 396s | 58.7 | 65.3 | 4,008,425 | inconsistent (2 runs failed) |
| planbuild-p_qwen35-b_dsv4 | qwen3.5-122b-a10b → deepseek-v4-flash | 1/3 | 98% | 98% | 294s | 39.0 | 43.0 | 2,394,662 | inconsistent (2 runs failed) |
| planbuild-p_coder-b_dsv4 | qwen3-coder-next → deepseek-v4-flash | 3/3 | 97% | 98% | 1159s | 101.3 | 100.3 | 8,302,643 | consistent |
| planbuild-ds4-coder 💀 | deepseek-v4-flash → qwen3-coder-next | 0/3 | 0% | 0% | 65s | 12.0 | 15.3 | 655,760 | all runs failed (0/200) |
| planbuild-p_mistral-b_coder 💀 | mistral-medium-3.5-128b → qwen3-coder-next | 0/3 | 0% | 0% | 199s | 14.3 | 17.7 | 800,536 | all runs failed (0/200) |

## Per-Combo Detail

| Combo | Repeat | Score | Wall | API Req | Tools | In Tokens | Out Tokens | Phase Breakdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| planbuild | r1 | 0/200 | 456.6s | 10 | 14 | 403,431 | 3,180 | plan(136.5s/9steps) → build(320.1s/1steps) |
| planbuild | r1 | 0/200 | 507.5s | 19 | 28 | 1,353,968 | 29,666 | plan(139.6s/6steps) → build(367.9s/13steps) |
| planbuild | r1 | 198/200 | 931.1s | 128 | 127 | 10,266,997 | 62,504 | plan(59.0s/3steps) → build(872.1s/125steps) |
| planbuild-ds4-coder | r1 | 0/200 | 43.8s | 9 | 9 | 437,392 | 1,558 | plan(31.2s/6steps) → build(12.6s/3steps) |
| planbuild-ds4-coder | r1 | 0/200 | 71.5s | 15 | 19 | 735,737 | 2,353 | plan(49.6s/13steps) → build(21.9s/2steps) |
| planbuild-ds4-coder | r1 | 0/200 | 79.8s | 12 | 18 | 794,152 | 2,284 | plan(52.4s/9steps) → build(27.4s/3steps) |
| planbuild-dsv4 | r1 | 197/200 | 1581.3s | 145 | 143 | 11,413,776 | 72,033 | plan(29.4s/3steps) → build(1551.9s/142steps) |
| planbuild-dsv4 | r1 | 0/200 | 95.0s | 14 | 25 | 835,042 | 2,575 | plan(56.6s/12steps) → build(38.4s/2steps) |
| planbuild-dsv4 | r1 | 200/200 | 456.5s | 31 | 40 | 2,417,954 | 38,255 | plan(54.8s/9steps) → build(401.7s/22steps) |
| planbuild-p_coder-b_coder | r1 | 199/200 | 714.8s | 52 | 51 | 4,589,472 | 59,576 | plan(34.5s/3steps) → build(680.3s/49steps) |
| planbuild-p_coder-b_coder | r1 | 200/200 | 304.2s | 22 | 28 | 1,187,906 | 28,301 | plan(38.7s/9steps) → build(265.5s/13steps) |
| planbuild-p_coder-b_coder | r1 | 198/200 | 734.1s | 112 | 110 | 7,492,691 | 64,322 | plan(34.8s/3steps) → build(699.3s/109steps) |
| planbuild-p_coder-b_dsv4 | r1 | 195/200 | 1114.0s | 118 | 118 | 8,992,555 | 77,987 | plan(21.9s/3steps) → build(1092.1s/115steps) |
| planbuild-p_coder-b_dsv4 | r1 | 193/200 | 1209.7s | 96 | 94 | 8,718,799 | 60,078 | plan(89.3s/3steps) → build(1120.4s/93steps) |
| planbuild-p_coder-b_dsv4 | r1 | 192/200 | 1153.2s | 90 | 89 | 7,196,576 | 75,588 | plan(106.8s/2steps) → build(1046.4s/88steps) |
| planbuild-p_coder-b_glm47 | r1 | 0/200 | 257.8s | 18 | 25 | 1,178,232 | 5,753 | plan(151.5s/13steps) → build(106.3s/5steps) |
| planbuild-p_coder-b_glm47 | r1 | 0/200 | 635.5s | 22 | 31 | 1,724,514 | 8,169 | plan(513.0s/13steps) → build(122.5s/9steps) |
| planbuild-p_coder-b_glm47 | r1 | 200/200 | 659.1s | 16 | 19 | 976,346 | 15,039 | plan(129.0s/13steps) → build(530.1s/3steps) |
| planbuild-p_coder-b_qwen36 | r1 | 196/200 | 1171.8s | 79 | 77 | 6,881,744 | 72,010 | plan(19.5s/3steps) → build(1152.3s/76steps) |
| planbuild-p_coder-b_qwen36 | r1 | 198/200 | 662.7s | 88 | 86 | 5,517,660 | 61,918 | plan(38.6s/3steps) → build(624.1s/85steps) |
| planbuild-p_coder-b_qwen36 | r1 | 200/200 | 318.1s | 24 | 29 | 1,259,860 | 28,277 | plan(70.5s/12steps) → build(247.6s/12steps) |
| planbuild-p_mistral-b_coder | r1 | 0/200 | 178.2s | 23 | 33 | 1,434,864 | 11,858 | plan(56.3s/7steps) → build(121.9s/16steps) |
| planbuild-p_mistral-b_coder | r1 | 0/200 | 82.1s | 15 | 16 | 879,532 | 2,836 | plan(49.0s/9steps) → build(33.1s/6steps) |
| planbuild-p_mistral-b_coder | r1 | 0/200 | 337.5s | 5 | 4 | 87,214 | 2,687 | plan(27.4s/4steps) → build(310.1s/1steps) |
| planbuild-p_mistral-b_dsv4 | r1 | 198/200 | 1060.5s | 143 | 141 | 12,767,463 | 86,204 | plan(29.8s/3steps) → build(1030.7s/140steps) |
| planbuild-p_mistral-b_dsv4 | r1 | 0/200 | 99.8s | 15 | 29 | 1,009,851 | 2,803 | plan(57.2s/11steps) → build(42.6s/4steps) |
| planbuild-p_mistral-b_dsv4 | r1 | 198/200 | 1781.5s | 121 | 119 | 9,076,286 | 68,775 | plan(22.2s/3steps) → build(1759.3s/118steps) |
| planbuild-p_mistral-b_glm47 | r1 | 0/200 | 104.0s | 16 | 29 | 1,131,941 | 3,493 | plan(61.6s/12steps) → build(42.4s/4steps) |
| planbuild-p_mistral-b_glm47 | r1 | 0/200 | 273.6s | 44 | 53 | 3,093,163 | 18,085 | plan(107.0s/13steps) → build(166.6s/31steps) |
| planbuild-p_mistral-b_glm47 | r1 | 197/200 | 811.4s | 116 | 114 | 7,800,171 | 59,560 | plan(30.4s/3steps) → build(781.0s/113steps) |
| planbuild-p_mistral-b_qwen36 | r1 | 0/200 | 59.9s | 7 | 9 | 319,706 | 1,473 | plan(40.9s/5steps) → build(19.0s/2steps) |
| planbuild-p_mistral-b_qwen36 | r1 | 197/200 | 1394.5s | 112 | 110 | 8,816,852 | 72,091 | plan(104.2s/3steps) → build(1290.3s/109steps) |
| planbuild-p_mistral-b_qwen36 | r1 | 0/200 | 123.2s | 18 | 30 | 1,157,453 | 5,604 | plan(83.0s/13steps) → build(40.2s/5steps) |
| planbuild-p_qwen35-b_coder | r1 | 0/200 | 84.4s | 9 | 11 | 425,456 | 4,278 | plan(53.3s/4steps) → build(31.1s/5steps) |
| planbuild-p_qwen35-b_coder | r1 | 194/200 | 684.6s | 92 | 92 | 6,402,445 | 63,038 | plan(28.4s/3steps) → build(656.2s/89steps) |
| planbuild-p_qwen35-b_coder | r1 | 200/200 | 387.8s | 22 | 31 | 1,317,888 | 26,317 | plan(38.3s/7steps) → build(349.5s/15steps) |
| planbuild-p_qwen35-b_dsv4 | r1 | 195/200 | 687.0s | 81 | 80 | 5,214,351 | 48,088 | plan(34.5s/4steps) → build(652.5s/77steps) |
| planbuild-p_qwen35-b_dsv4 | r1 | 0/200 | 78.7s | 15 | 21 | 930,055 | 2,276 | plan(45.6s/11steps) → build(33.1s/4steps) |
| planbuild-p_qwen35-b_dsv4 | r1 | 0/200 | 117.6s | 21 | 28 | 1,039,582 | 5,179 | plan(76.6s/12steps) → build(41.0s/9steps) |
| planbuild-p_qwen35-b_glm47 | r1 | 0/200 | 82.5s | 17 | 21 | 855,503 | 2,758 | plan(63.6s/12steps) → build(18.9s/5steps) |
| planbuild-p_qwen35-b_glm47 | r1 | 198/200 | 987.0s | 91 | 89 | 6,132,171 | 60,348 | plan(27.7s/3steps) → build(959.3s/88steps) |
| planbuild-p_qwen35-b_glm47 | r1 | 0/200 | 113.2s | 11 | 21 | 842,871 | 4,429 | plan(72.7s/7steps) → build(40.5s/4steps) |
| planbuild-p_qwen35-b_qwen36 | r1 | 0/200 | 88.0s | 18 | 28 | 1,256,803 | 3,312 | plan(40.6s/8steps) → build(47.4s/10steps) |
| planbuild-p_qwen35-b_qwen36 | r1 | 200/200 | 280.7s | 14 | 14 | 724,590 | 29,733 | plan(42.9s/7steps) → build(237.8s/7steps) |
| planbuild-p_qwen35-b_qwen36 | r1 | 197/200 | 1118.1s | 132 | 131 | 13,007,322 | 94,756 | plan(45.0s/3steps) → build(1073.1s/129steps) |

## Key Takeaways

- **45 total runs** across 15 combos (3 repeats each)
- **45 runs** produced meaningful test results (0 were invalid/provider errors)
- **22 runs** scored 0/200 — agent produced broken code (couldn't even import)
- **6 runs** scored 200/200 (perfect)
- The benchmark is now discriminating well: scores range from **0% to 100%** across combos
- **planbuild-p_coder-b_coder** (qwen3-coder-next plan+build) is the standout: 3/3 consistent, 100% best score
- **planbuild-p_coder-b_qwen36**: 3/3 consistent, 200/200 best
- **planbuild-p_coder-b_dsv4**: 3/3 consistent, 195-200/200
- **planbuild-ds4-coder** (dsv4→coder) and **planbuild-p_mistral-b_coder**: 💀 0/3, all runs failed
