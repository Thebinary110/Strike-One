# The 2x2 leakage table (IEEE-CIS, minimal card1 aggregates)

## Average precision

| split \ aggregates | whole-dataset | expanding (point-in-time) |
|---|---|---|
| **random** | 0.7976 [0.7837, 0.8108] ⚠ BOTH LEAKS | 0.7862 [0.7720, 0.7993] (split leak only) |
| **chronological** | 0.5725 [0.5530, 0.5903] (agg leak only) | **0.5734 [0.5540, 0.5910] ← HONEST** |

- split leak: **+0.2128**
- aggregation leak: **-0.0009**
- interaction: +0.0123
- total inflation: **+0.2242**

## ROC-AUC

| split \ aggregates | whole-dataset | expanding (point-in-time) |
|---|---|---|
| **random** | 0.9592 [0.9547, 0.9636] ⚠ BOTH LEAKS | 0.9560 [0.9513, 0.9605] (split leak only) |
| **chronological** | 0.9208 [0.9153, 0.9261] (agg leak only) | **0.9196 [0.9138, 0.9250] ← HONEST** |

- split leak: **+0.0364**
- aggregation leak: **+0.0012**
- interaction: +0.0019
- total inflation: **+0.0396**
