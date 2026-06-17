# DS Permutation Swarm - WIN-Anchor Report (DSP1)

top_k=6 min_item_n=5 modes=ARAM,SR

## Aggregate

- champ-mode considered: 341
- champ-mode scored (DS-favored items have rewind data): 294
- positive lift (DS favors winners): 160 (54.42%)
- mean lift weighted-by-games: 0.1679
- mean lift unweighted: 0.8545

## Top outcome-aligned (champ x mode, by mean lift)

| champ | mode | n | baseline_wr | mean_lift |
|---|---|---|---|---|
| Xerath | SR | 27 | 33.3333 | 38.6364 |
| Graves | SR | 82 | 56.0976 | 32.7913 |
| Zac | SR | 32 | 53.125 | 28.6932 |
| Yorick | ARAM | 51 | 52.9412 | 27.0588 |
| Talon | SR | 34 | 35.2941 | 24.7059 |
| Galio | SR | 63 | 58.7302 | 24.6031 |
| Zed | SR | 52 | 51.9231 | 21.7457 |
| Velkoz | SR | 28 | 60.7143 | 21.2987 |
| Fiora | SR | 81 | 58.0247 | 20.5467 |
| Sivir | ARAM | 163 | 44.1718 | 20.4436 |
| Orianna | SR | 37 | 40.5405 | 17.2258 |
| Singed | ARAM | 76 | 48.6842 | 16.8004 |
| Akali | ARAM | 118 | 36.4407 | 16.6174 |
| Teemo | SR | 29 | 68.9655 | 16.2977 |
| Nami | SR | 63 | 65.0794 | 16.1706 |
| Kassadin | SR | 25 | 44.0 | 16.0 |
| DrMundo | SR | 18 | 50.0 | 15.5911 |
| Katarina | SR | 40 | 52.5 | 15.5 |
| Varus | SR | 45 | 40.0 | 15.0 |
| Elise | SR | 27 | 29.6296 | 14.8148 |
| Aatrox | ARAM | 137 | 45.2555 | 14.7445 |
| MissFortune | SR | 61 | 59.0164 | 14.6043 |
| Shaco | SR | 47 | 42.5532 | 14.5897 |
| Nidalee | SR | 27 | 25.9259 | 14.5185 |
| Janna | ARAM | 124 | 57.2581 | 13.7832 |

## Most outcome-divergent (DS favors losers, by lowest lift)

| champ | mode | n | baseline_wr | mean_lift |
|---|---|---|---|---|
| Ezreal | SR | 92 | 39.1304 | -39.1304 |
| Zilean | ARAM | 125 | 52.8 | -32.8 |
| Rammus | SR | 10 | 70.0 | -30.0 |
| Shaco | ARAM | 124 | 52.4194 | -29.2143 |
| Pyke | ARAM | 150 | 52.0 | -22.0 |
| Udyr | ARAM | 56 | 42.8571 | -21.6988 |
| Nilah | ARAM | 83 | 54.2169 | -20.8836 |
| Gragas | SR | 39 | 41.0256 | -18.8034 |
| Rengar | SR | 36 | 50.0 | -18.3333 |
| Nautilus | SR | 83 | 59.0361 | -17.7028 |
| Zaahen | SR | 7 | 57.1429 | -17.1429 |
| Vex | SR | 18 | 50.0 | -16.6667 |
| Kayle | ARAM | 143 | 53.8462 | -16.3462 |
| TwistedFate | ARAM | 147 | 55.7823 | -15.8688 |
| Diana | SR | 66 | 48.4848 | -15.6277 |
| Seraphine | ARAM | 136 | 56.6176 | -14.9509 |
| Rakan | ARAM | 61 | 39.3443 | -13.5548 |
| Katarina | ARAM | 152 | 50.6579 | -13.0248 |
| Kaisa | SR | 89 | 42.6966 | -12.9996 |
| Leblanc | SR | 32 | 40.625 | -12.0536 |
| Briar | ARAM | 38 | 52.6316 | -11.6594 |
| Singed | SR | 20 | 40.0 | -11.4286 |
| Caitlyn | ARAM | 262 | 50.3817 | -10.9272 |
| KSante | SR | 33 | 45.4545 | -10.6926 |
| Yasuo | ARAM | 143 | 41.958 | -10.5172 |
