---
license: other
base_model: nvidia/Riva-Translate-4B-Instruct-v2
pipeline_tag: text-generation
tags:
- gguf
- local-llm
- llama.cpp
- lm-studio
- quantized
- imatrix
- sub-4-bit
- mistral
- base_model:nvidia/Mistral-NeMo-12B-Base
---

# Riva-Translate-4B-Instruct-v2 — iMatrix GGUF

GGUF quantizations of [nvidia/Riva-Translate-4B-Instruct-v2](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2), published by [Liodon AI](https://huggingface.co/liodon-ai).

## Quick Start

**llama.cpp**
```bash
llama-cli -hf liodon-ai/Riva-Translate-4B-Instruct-v2-imatrix-GGUF:Q4_K_M
```

**Ollama**
```bash
ollama run hf.co/liodon-ai/Riva-Translate-4B-Instruct-v2-imatrix-GGUF:Q4_K_M
```

**LM Studio / Jan** — search `liodon-ai/Riva-Translate-4B-Instruct-v2-imatrix-GGUF` and pick your quant.

## Quants

| Quant | Size | VRAM est. | Notes |
|-------|------|-----------|-------|
| `IQ2_M` | 1.79 GB | ~2 GB | 2-bit, iMatrix — smallest usable |
| `IQ3_M` | 2.17 GB | ~2 GB | 3-bit, iMatrix — great quality/size tradeoff |
| `IQ4_XS` | 2.39 GB | ~3 GB | 4-bit extra-small, iMatrix |
| `Q4_K_M` | 2.76 GB | ~3 GB | 4-bit, iMatrix-calibrated (recommended) |
| `Q5_K_M` | 3.14 GB | ~4 GB | 5-bit, iMatrix-calibrated |
| `Q6_K` | 3.66 GB | ~4 GB | 6-bit, iMatrix-calibrated, near-lossless |
| `Q8_0` | 4.45 GB | ~5 GB | 8-bit, essentially lossless |


## What is iMatrix?

Standard quantization treats all weights equally. iMatrix runs 128 calibration chunks through
the full-precision model to find which weights matter most, then allocates more precision where
it counts. At Q2/Q3/Q4 this means noticeably better coherence and instruction-following —
**same file size, better output**.

Calibration: 2M tokens of [WikiText-103](https://huggingface.co/datasets/wikitext).

> Also see plain (non-iMatrix) quants: `liodon-ai/Riva-Translate-4B-Instruct-v2-GGUF`

## Source

- **Model**: [nvidia/Riva-Translate-4B-Instruct-v2](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2)
- **License**: other

---
*Quantized by [Liodon AI](https://huggingface.co/liodon-ai)*
