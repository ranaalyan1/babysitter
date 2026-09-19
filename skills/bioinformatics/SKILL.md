---
name: bioinformatics
description: Bioinformatics pipeline conventions for NGS data (FASTQ/BAM/VCF), QC, and reproducibility. Use when building or reviewing genomics/NGS analysis pipelines.
license: MIT
compatibility: Assumes samtools/bcftools and a Python 3.11+ environment are available.
allowed-tools: filesystem.read filesystem.write terminal.run
metadata:
  category: science
  test0.tags: bioinformatics,science,python
---
# Bioinformatics Skill

## When to use this skill
Building, reviewing, or debugging a genomics/NGS analysis pipeline.

## Instructions
1. Use established formats — FASTQ, BAM/SAM, VCF — and validate them
   with `samtools`/`bcftools` rather than hand-rolled parsers where possible.
2. Prefer a reproducible pipeline framework (Snakemake or Nextflow) over
   ad hoc shell scripts for anything with more than two sequential steps.
3. Record the reference genome build and every tool's version in output
   metadata so results are traceable.
4. Run QC (e.g. FastQC) as a distinct step before the main analysis and
   fail fast on QC issues rather than analyzing low-quality input.
