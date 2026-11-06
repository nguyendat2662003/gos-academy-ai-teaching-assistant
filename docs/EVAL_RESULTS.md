# Kết quả đánh giá RAG

- Bộ câu hỏi: `data/eval/golden.yaml` (40 câu)
- Embedding: `openai:text-embedding-3-small` (dim 768); top_k = 5
- LLM: `openai:gpt-6-luna`; RETRIEVAL_MIN_SCORE = 0.35

## Truy xuất

| Chỉ số | Giá trị |
|---|---|
| hit@1 | 26/30 (87%) |
| hit@5 | 30/30 (100%) |
| MRR@5 | 0.933 |
| Chunk lớp khác bị truy xuất (phải = 0) | **0** |

## Ngưỡng `RETRIEVAL_MIN_SCORE` (cosine top-1)

- Câu có căn cứ: min **0.391**, trung vị 0.586, max 0.786
- Câu ngoài giáo trình / lớp khác: min 0.333, max **0.642**

| Ngưỡng | Câu có căn cứ qua cổng | Câu không căn cứ bị chặn ngay (không gọi LLM) |
|---|---|---|
| 0.20 | 30/30 (100%) | 0/6 (0%) |
| 0.25 | 30/30 (100%) | 0/6 (0%) |
| 0.30 | 30/30 (100%) | 0/6 (0%) |
| 0.35 | 30/30 (100%) | 2/6 (33%) |
| 0.40 | 28/30 (93%) | 3/6 (50%) |
| 0.45 | 25/30 (83%) | 3/6 (50%) |
| 0.50 | 23/30 (77%) | 3/6 (50%) |
| 0.55 | 22/30 (73%) | 4/6 (67%) |
| 0.60 | 14/30 (47%) | 4/6 (67%) |

Đề xuất: ngưỡng cao nhất vẫn cho **mọi** câu có căn cứ qua cổng, trừ biên 0.03 → **0.36**. Câu không căn cứ lọt qua cổng vẫn bị chặn ở bước kiểm tra JSON/trích dẫn (D-60).

## Pipeline đầy đủ (LLM thật)

| Chỉ số | Giá trị |
|---|---|
| Quyết định đúng (khớp chính xác `expect`) | 40/40 (100%) |
| Quyết định trả lời/không trả lời đúng | 40/40 (100%) |
| Trả lời câu lẽ ra phải chuyển/từ chối (bịa) | **0** |
| Trích dẫn đúng mục kỳ vọng (trong số câu đã trả lời) | 30/30 (100%) |
| Trích dẫn chunk lớp khác (phải = 0) | **0** |
| Token LLM (vào + ra) | 69094 |
| Thời gian xử lý TB / câu (không gồm hàng đợi) | 2159 ms |

| Theo loại | Đúng |
|---|---|
| injection | 2/2 (100%) |
| material | 30/30 (100%) |
| not_in_material | 4/4 (100%) |
| other_class | 2/2 (100%) |
| policy | 2/2 (100%) |

| id | lớp | kỳ vọng | kết quả | lý do | top | mục trích dẫn |
|---|---|---|---|---|---|---|
| GS-01 | GS-KPI-01 | answer | answered |  | 0.745 | GS-02 |
| GS-02 | GS-KPI-01 | answer | answered |  | 0.562 | GS-02 |
| GS-03 | GS-KPI-01 | answer | answered |  | 0.430 | GS-02 |
| GS-04 | GS-KPI-01 | answer | answered |  | 0.601 | GS-03 |
| GS-05 | GS-KPI-01 | answer | answered |  | 0.629 | GS-03 |
| GS-06 | GS-KPI-01 | answer | answered |  | 0.611 | GS-CLASS-02, GS-04 |
| GS-07 | GS-KPI-01 | answer | answered |  | 0.578 | GS-04 |
| GS-08 | GS-KPI-01 | answer | answered |  | 0.558 | GS-01 |
| GS-09 | GS-KPI-01 | answer | answered |  | 0.607 | GS-CLASS-02, GS-01 |
| GS-10 | GS-KPI-01 | answer | answered |  | 0.558 | GS-05 |
| GS-11 | GS-KPI-01 | answer | answered |  | 0.444 | GS-06 |
| GS-12 | GS-KPI-01 | answer | answered |  | 0.391 | GS-07 |
| GS-13 | GS-KPI-01 | answer | answered |  | 0.682 | GS-CLASS-02, GS-02 |
| GS-14 | GS-KPI-01 | answer | answered |  | 0.470 | GS-CLASS-01 |
| GS-15 | GS-KPI-01 | answer | answered |  | 0.699 | GS-CLASS-01, GS-CLASS-02 |
| GS-16 | GS-KPI-01 | answer | answered |  | 0.586 | COMMON-02 |
| GS-17 | GS-KPI-01 | handoff | handoff | low_confidence | 0.642 |  |
| GS-18 | GS-KPI-01 | handoff | handoff | low_confidence | 0.606 |  |
| GS-19 | GS-KPI-01 | handoff (policy) | handoff | policy | 0.413 |  |
| GS-20 | GS-KPI-01 | handoff | handoff | no_context | 0.333 |  |
| GS-21 | GS-KPI-01 | refused | refused |  | – |  |
| AU-01 | AUTO-N8N-01 | answer | answered |  | 0.786 | AUTO-01 |
| AU-02 | AUTO-N8N-01 | answer | answered |  | 0.722 | AUTO-02 |
| AU-03 | AUTO-N8N-01 | answer | answered |  | 0.641 | AUTO-02, AUTO-CLASS-02 |
| AU-04 | AUTO-N8N-01 | answer | answered |  | 0.544 | AUTO-03 |
| AU-05 | AUTO-N8N-01 | answer | answered |  | 0.640 | AUTO-03, AUTO-07 |
| AU-06 | AUTO-N8N-01 | answer | answered |  | 0.659 | AUTO-03, AUTO-CLASS-02 |
| AU-07 | AUTO-N8N-01 | answer | answered |  | 0.688 | AUTO-04, AUTO-CLASS-02 |
| AU-08 | AUTO-N8N-01 | answer | answered |  | 0.574 | AUTO-04 |
| AU-09 | AUTO-N8N-01 | answer | answered |  | 0.469 | AUTO-05 |
| AU-10 | AUTO-N8N-01 | answer | answered |  | 0.581 | AUTO-07 |
| AU-11 | AUTO-N8N-01 | answer | answered |  | 0.579 | AUTO-08 |
| AU-12 | AUTO-N8N-01 | answer | answered |  | 0.449 | AUTO-CLASS-01 |
| AU-13 | AUTO-N8N-01 | answer | answered |  | 0.701 | AUTO-CLASS-01, AUTO-CLASS-02 |
| AU-14 | AUTO-N8N-01 | partial | partial | partial_coverage | 0.394 | AUTO-05 |
| AU-15 | AUTO-N8N-01 | handoff | handoff | low_confidence | 0.518 |  |
| AU-16 | AUTO-N8N-01 | handoff | handoff | no_context | 0.348 |  |
| AU-17 | AUTO-N8N-01 | handoff (policy) | handoff | policy | 0.506 |  |
| AU-18 | AUTO-N8N-01 | handoff | handoff | low_confidence | 0.370 |  |
| AU-19 | AUTO-N8N-01 | refused | refused |  | – |  |

