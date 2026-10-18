# Retrieval Comparison

Generated: `2026-10-18T10:55:43.857229+00:00`. Thresholds tuned on 33 dev cases; metrics below are on 45 held-out cases.

| Config | MRR | hit@1 | recall@3 | Accept answerable | Reject unanswerable | Balanced | Evidence recall | ms/query |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A_current_minilm_chunk_threshold | 0.857 | 0.781 | 0.906 | 0.594 | 0.692 | 0.643 | 0.516 | 20.8 |
| B_minilm_recalibrated_threshold | 0.857 | 0.781 | 0.906 | 0.844 | 0.615 | 0.730 | 0.781 | 50.0 |
| C_minilm_dense_top1_gate | 0.857 | 0.781 | 0.906 | 0.844 | 0.615 | 0.730 | 0.812 | 25.0 |
| D_minilm_bm25_rrf | 0.907 | 0.844 | 0.953 | 0.812 | 0.615 | 0.714 | 0.797 | 28.2 |
| E_minilm_bm25_msmarco_rerank | 0.885 | 0.812 | 0.984 | 0.562 | 0.769 | 0.666 | 0.562 | 878.0 |
| F_bge_small_bm25_msmarco_rerank | 0.885 | 0.812 | 0.984 | 0.562 | 0.769 | 0.666 | 0.562 | 892.5 |
| G_e5_small_bm25_msmarco_rerank | 0.885 | 0.812 | 0.984 | 0.562 | 0.769 | 0.666 | 0.562 | 847.4 |
| H_e5_small_bm25_rrf | 0.912 | 0.844 | 0.953 | 0.938 | 0.615 | 0.776 | 0.891 | 106.4 |
| I_minilm_bm25_mmarco_multilingual_rerank | 0.918 | 0.875 | 0.953 | 0.625 | 0.692 | 0.659 | 0.625 | 1446.0 |
