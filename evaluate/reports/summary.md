# Evaluation Report

## Methodology

Benchmarks are run against the core logic of the aurum repository. Token counts use a consistent `len(text) // 4` approximation. Impact accuracy uses graph edges as ground truth.

## Token Efficiency Analysis: Graph vs. Blind Search

Measuring how effectively the `code-review-graph` filters out irrelevant code during the strategy fix.

| Search Strategy | Scope | Tokens Consumed | Noise Reduction |
| :--- | :--- | :--- | :--- |
| **Blind Agent** | Read all `core/` logic | 21,614 | Baseline |
| **Standard Agent** | Git Diff (review only) | 1,285 | 94.1% |
| **Graph-Guided** | Impact analysis (2 files) | **4,023** | **81.4%** |

### ROI Summary
- **Total Saving**: **17,591 tokens** per turn.
- **Why**: The graph bypassed 80% of the `core/` directory by identifying that indicators, calendar, macro, and report logic were NOT part of the blast radius for this specific bug.
