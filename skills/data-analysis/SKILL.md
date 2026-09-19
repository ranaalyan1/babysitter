---
name: data-analysis
description: Conventions for exploring and analyzing tabular or numeric data. Use when asked to analyze a dataset, CSV, or produce statistics/charts from data.
license: MIT
allowed-tools: filesystem.read terminal.run
metadata:
  category: data
  test0.tags: data,analysis
---
# Data Analysis Skill

## When to use this skill
Analyzing a dataset, computing statistics, or producing charts/summaries
from tabular or numeric data.

## Instructions
1. Inspect shape, dtypes, and missing values before doing any analysis.
2. Prefer vectorized operations (pandas/numpy) over manual Python loops.
3. State assumptions and limitations explicitly alongside any
   statistical claim (sample size, confounders, etc.).
4. Visualize distributions before summarizing with a single statistic
   like a mean — outliers and skew change the right summary.
