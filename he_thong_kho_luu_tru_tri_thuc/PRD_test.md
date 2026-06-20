
# 1. Functional Requirements

## 1.1. Phạm vi kỹ thuật áp dụng cho v1

| Layer | Kỹ thuật áp dụng trong v1 | Ghi chú |
|---|---|---|
| Query Understanding | Intent classification, Query routing | Bắt buộc |
| Query Optimization | Query rewrite, Query expansion | Bắt buộc |
| Query Optimization | Query decomposition | Chỉ kích hoạt cho truy vấn phức tạp |
| Retrieval | BM25 + Vector search + Hybrid search | Bắt buộc |
| Ranking | Cross-encoder reranker | Bắt buộc cho top results |
| Context Optimization | Filtering, Compression | Bắt buộc |
| Generation | Grounding, Citation, Verification | Bắt buộc |

> Ghi chú: v1 **không triển khai toàn bộ kỹ thuật AI nâng cao có thể có**, mà ưu tiên stack thực dụng, dễ kiểm soát chất lượng, chi phí và vận hành.

---

## 1.2. Functional Requirements chi tiết

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---:|---|
| FR-03 | **Quản lý metadata tài liệu** | P0 | Mỗi tài liệu có tối thiểu: tiêu đề, khoa/viện, loại tài liệu, tác giả/đơn vị ban hành, ngày ban hành, phiên bản, trạng thái hiệu lực, quyền truy cập |
| FR-05 | **Phân loại ý định truy vấn (intent classification)** | P0 | Hệ thống nhận diện tối thiểu 4 intent: (1) tìm tài liệu cụ thể, (2) tìm theo chủ đề |
| FR-06 | **Điều hướng truy vấn (query routing)** theo intent | P0 | Query “tìm tên văn bản cụ thể” ưu tiên lexical/BM25; query hỏi đáp dùng hybrid + generation; query tạo tài liệu đi vào flow template + retrieval |
| FR-07 | **Tối ưu truy vấn bằng rewrite** | P0 | Hệ thống tự sửa lỗi chính tả phổ biến, chuẩn hóa cách diễn đạt, và tạo rewritten query nội bộ trước khi search |
| FR-08 | **Mở rộng truy vấn (query expansion)** | P0 | Hệ thống hỗ trợ synonym/viết tắt/biến thể thuật ngữ theo ngữ cảnh khoa/viện; ví dụ tên đơn vị, quy chế, biểu mẫu |
| FR-09 | **Tách truy vấn phức tạp (query decomposition)** khi cần | P1 | Với truy vấn dài hoặc nhiều ý, hệ thống tách thành sub-query để tăng recall; chỉ áp dụng khi confidence vượt ngưỡng cấu hình |
| FR-10 | **Tìm kiếm hybrid** kết hợp BM25 và vector search | P0 | Kết quả tìm kiếm được hợp nhất từ lexical match + semantic match; hỗ trợ tìm theo từ khóa chính xác và theo nghĩa |
| FR-11 | **Hỗ trợ lọc tìm kiếm theo metadata** | P0 | Cho phép filter tối thiểu theo: khoa/viện, loại tài liệu, năm, trạng thái hiệu lực, tác giả/đơn vị ban hành |
| FR-12 | **Xếp hạng kết quả bằng reranker/cross-encoder** | P0 | Hệ thống lấy top-K từ retrieval và rerank lại để tăng độ liên quan; kết quả top đầu phải phản ánh tốt hơn ngữ nghĩa truy vấn |
| FR-13 | **Hiển thị kết quả tìm kiếm có ngữ cảnh** | P0 | Mỗi kết quả hiển thị: tiêu đề, metadata chính, snippet liên quan, vị trí match, loại tài liệu, ngày ban hành |
| FR-14 | **Xem trước và mở tài liệu tại đoạn liên quan** | P0 | Khi người dùng bấm kết quả, hệ thống mở được tài liệu hoặc preview và highlight đoạn liên quan nếu khả thi |
| FR-16 | **Trích dẫn nguồn (citation)** trong câu trả lời AI | P0 | Mỗi câu trả lời AI phải kèm citation tới tài liệu nguồn; tối thiểu gồm tên tài liệu và đoạn/chunk tham chiếu |
| **FR-17** | **Kiểm tra tính xác thực đầu ra (verification)** | P2 | Nếu bằng chứng yếu, mâu thuẫn, hoặc không đủ, hệ thống phải cảnh báo “không đủ căn cứ” thay vì trả lời chắc chắn |
| FR-22 | **Quản lý phiên bản tài liệu và lịch sử chỉnh sửa** | P1 | Tài liệu có version, người sửa cuối, thời gian sửa, và có thể xem lịch sử thay đổi |
| FR-23 | **Thu thập feedback người dùng** với kết quả search/AI answer | P0 | Có cơ chế thumbs up/down, báo sai nguồn, báo không liên quan, báo thiếu tài liệu |
| FR-24 | **Dashboard quản trị và đánh giá chất lượng** | P1 | Admin xem được: query phổ biến, zero-result queries, CTR, feedback xấu, chất lượng theo khoa/viện |
| **FR-25** | **Quản trị từ điển thuật ngữ/synonym/viết tắt** | P2 | Admin có thể thêm/sửa danh mục synonym, alias tên đơn vị, tên văn bản, thuật ngữ chuyên ngành |

---

# 2. Non-functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | **Hiệu năng tìm kiếm** | P95 latency cho search-only ≤ 2.5 giây |
| NFR-02 | **Hiệu năng hỏi đáp có AI** | P95 latency cho search + answer generation ≤ 8 giây |
| NFR-03 | **Tính sẵn sàng hệ thống** | Uptime ≥ 99.5%/tháng |
| NFR-04 | **Khả năng mở rộng** | Hỗ trợ tối thiểu 500,000 tài liệu, 5 triệu chunks, 200 người dùng đồng thời mà không cần thay đổi kiến trúc lõi |
| NFR-05 | **Độ tươi của chỉ mục** | Tài liệu mới hoặc cập nhật phải searchable trong vòng ≤ 30 phút sau khi ingest thành công |
| NFR-06 | **Bảo mật truy cập** | Tích hợp SSO/LDAP/OAuth2 nếu có; bắt buộc RBAC; mọi request được kiểm soát quyền trước khi trả kết quả |
| NFR-07 | **Mã hóa dữ liệu** | Mã hóa in-transit bằng TLS; mã hóa at-rest cho dữ liệu nhạy cảm |
| NFR-08 | **Auditability** | Lưu audit log cho upload, search, generate, xem tài liệu, thay đổi quyền, thay đổi metadata |
| NFR-09 | **Khả năng truy vết câu trả lời AI** | Mỗi câu trả lời phải lưu được dấu vết: query gốc, rewritten query, retrieved docs, reranked docs, citations đã dùng |
| NFR-10 | **Độ tin cậy khi lỗi thành phần AI** | Nếu vector service, reranker, hoặc LLM lỗi, hệ thống phải fallback về search cơ bản thay vì dừng toàn bộ dịch vụ |
| NFR-11 | **Hỗ trợ tiếng Việt tốt** | Tìm kiếm không dấu/có dấu; xử lý viết tắt, biến thể chính tả, thuật ngữ nội bộ phổ biến |
| NFR-12 | **Tính dễ bảo trì và quan sát** | Có log, metric, tracing cho từng bước: ingest, retrieval, rerank, generation; hỗ trợ debug theo query/session |
| NFR-13 | **Cấu hình được chiến lược tìm kiếm** | Có thể thay đổi trọng số hybrid, top-K, ngưỡng confidence, routing rule mà không phải sửa code lõi |
| NFR-14 | **Khả năng tích hợp** | Cung cấp API để tích hợp với portal nội bộ, DMS, LMS, website khoa/viện |
| NFR-15 | **Khả năng sử dụng** | UI responsive, dễ dùng cho người không chuyên kỹ thuật; hỗ trợ desktop trước, mobile responsive ở mức cơ bản |
| NFR-16 | **An toàn nội dung AI** | Không cho phép AI tự bịa nguồn; nếu không có bằng chứng thì phải từ chối hoặc gợi ý refine query |
| NFR-17 | **Kiểm soát chi phí vận hành AI** | Có cơ chế context compression, caching và giới hạn token để tránh chi phí generate tăng không kiểm soát |
| NFR-18 | **Khả năng kiểm thử chất lượng** | Hệ thống phải hỗ trợ bộ eval queries/golden set để đo relevance, grounding, hallucination trước và sau mỗi thay đổi |

---

# 3. Success Metrics

> Đề xuất đo theo 2 lớp:
> 1. **Offline evaluation trước go-live**
> 2. **Online metrics sau 1–3 tháng pilot**

## 3.1. Offline Success Metrics

| Metric | Target |
|---|---:|
| Intent classification accuracy | ≥ 90% |
| Query routing accuracy | ≥ 85% |
| Precision@5 cho bài toán tìm tài liệu | ≥ 0.75 |
| NDCG@10 cho bài toán tìm kiếm chủ đề | ≥ 0.80 |
| MRR cho truy vấn tìm đúng tài liệu cụ thể | ≥ 0.85 |
| Tỷ lệ citation đúng nguồn trong AI answer | ≥ 95% |
| Tỷ lệ câu trả lời có citation | 100% |
| Tỷ lệ hallucination/unsupported claim qua human review | ≤ 5% |

---

## 3.2. Online/Product Success Metrics

| Metric | Target sau 3 tháng pilot |
|---|---:|
| Search success rate (người dùng tìm được kết quả hữu ích trong phiên) | ≥ 75% |
| Query reformulation rate | ≤ 25% |
| Zero-result rate | ≤ 8% |
| CTR vào top 3 kết quả đầu | ≥ 60% |
| Thời gian trung vị để tìm được tài liệu phù hợp | Giảm ≥ 50% so với hiện trạng |
| CSAT cho tính năng tìm kiếm tài liệu | ≥ 4.2/5 |
| Tỷ lệ người dùng đánh giá AI answer “hữu ích” | ≥ 80% |
| Tỷ lệ AI answer bị report “sai nguồn / không đúng” | ≤ 5% |

---

## 3.3. Operational Success Metrics

| Metric | Target |
|---|---:|
| P95 search latency | ≤ 2.5 giây |
| P95 answer generation latency | ≤ 8 giây |
| Uptime | ≥ 99.5% |
| Index freshness | ≤ 30 phút |
| Tỷ lệ lỗi pipeline ingest | ≤ 2% |
| Tỷ lệ fallback an toàn khi AI component lỗi | 100% có graceful fallback |
