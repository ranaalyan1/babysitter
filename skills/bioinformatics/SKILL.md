---
name: bioinformatics
version: 1.0.0
description: Bioinformatics pipeline conventions (NGS-oriented)
tags: [bioinformatics, science, python]
requiredTools: [filesystem.read, filesystem.write, terminal.run]
---
# Bioinformatics Skill

- Use established formats: FASTQ, BAM/SAM, VCF; validate with `samtools`/`bcftools` where applicable.
- Prefer reproducible pipelines (Snakemake/Nextflow) over ad hoc scripts for multi-step workflows.
- Record reference genome build and tool versions in output metadata.
- Separate QC steps (e.g. FastQC) from the main analysis and fail fast on QC issues.
