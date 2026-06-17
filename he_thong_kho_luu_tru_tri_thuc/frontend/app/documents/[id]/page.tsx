"use client";
import {
  BookOpen, ChevronDown, ChevronLeft, Download, FileText, Highlighter,
  Languages, LoaderCircle, MessageSquareText, Send, Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { API_URL, Document, formatDate } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";
import ReactMarkdown from "react-markdown";

const STORAGE_KEY = "eduvault_conversations";

/** Mỗi tài khoản có lịch sử chat riêng: khóa lưu trữ gắn theo mã giảng viên. */
function convStorageKey(code: string): string {
  return `${STORAGE_KEY}:${code}`;
}

type Provenance = {
  document: Document;
  versions: { id: string; version_no: number; created_by: string; created_at: string }[];
  sync_history: { id: string; status: string; detail: string; created_at: string }[];
  files: { id: string; version_no: number; original_name: string; mime_type: string; size: number; created_at: string }[];
  access: { type: "public" | "owner" | "approved_request"; request_id: string | null };
};

type Citation = { id: string; title: string; topic: string; current_version: number };
type ChatItem = { question: string; answer: string; citations: Citation[]; isPreset?: boolean };

const empty: Provenance = {
  document: { id: "", title: "", doc_type: "", topic: "", owner_code: "", visibility: "public", current_version: 0, created_at: "", updated_at: "", folder_path: "" },
  versions: [], sync_history: [], files: [],
  access: { type: "public", request_id: null },
};

function CitationToggle({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4 border-t border-[var(--border)] pt-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-[11px] text-[var(--muted)] hover:text-blue-600 transition-colors"
      >
        <FileText size={12}/>
        Nguồn tham khảo ({citations.length})
        <ChevronDown size={12} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}/>
      </button>
      {open && (
        <div className="mt-3 space-y-1">
          {citations.map(c => (
            <Link key={c.id} href={`/documents/${c.id}`} className="flex items-center gap-1.5 text-xs text-blue-600 hover:underline">
              <FileText size={11}/>{c.title}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function saveConvToStorage(code: string, convId: string, title: string, items: ChatItem[]) {
  if (!code) return;
  const key = convStorageKey(code);
  try {
    const stored = JSON.parse(localStorage.getItem(key) || "[]");
    const msgs = items.map(item => ({
      question: item.question,
      result: { answer: item.answer, citations: item.citations, scope: "accessible" },
    }));
    const entry = { id: convId, title, messages: msgs, updatedAt: Date.now() };
    const idx = stored.findIndex((c: { id: string }) => c.id === convId);
    if (idx >= 0) stored[idx] = entry;
    else stored.unshift(entry);
    if (stored.length > 30) stored.length = 30;
    localStorage.setItem(key, JSON.stringify(stored));
  } catch {}
}

export default function DocumentViewer() {
  const { id } = useParams<{ id: string }>();
  const { token, request, user } = useAuth();
  const { data, error } = useBackendData<Provenance>(`/api/documents/${id}/provenance`, empty);

  const [aiAction, setAiAction] = useState("");
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState("");
  const [convId, setConvId] = useState<string | null>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  async function askAI(action: string, prompt: string) {
    setAiAction(action);
    setChat([]);
    setChatError("");
    setChatLoading(true);
    const newId = crypto.randomUUID();
    setConvId(newId);
    try {
      const r = await request<{ answer: string; citations: Citation[] }>(
        "/api/search", { method: "POST", body: JSON.stringify({ question: prompt }) }
      );
      const item: ChatItem = { question: action, answer: r.answer, citations: r.citations, isPreset: true };
      setChat([item]);
      saveConvToStorage(user?.code ?? "", newId, `${action} · ${data.document.title}`, [item]);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "Không thể thực hiện.");
      setConvId(null);
    } finally {
      setChatLoading(false);
    }
  }

  async function sendChat(e: React.FormEvent) {
    e.preventDefault();
    const q = chatInput.trim();
    if (!q || chatLoading) return;
    setChatInput("");
    setChatError("");
    setChatLoading(true);
    const currentId = convId ?? (() => { const n = crypto.randomUUID(); setConvId(n); return n; })();
    try {
      const prompt = `Liên quan đến tài liệu "${data.document.title}" (chủ đề: ${data.document.topic}): ${q}`;
      const r = await request<{ answer: string; citations: Citation[] }>(
        "/api/search", { method: "POST", body: JSON.stringify({ question: prompt }) }
      );
      setChat(prev => {
        const updated = [...prev, { question: q, answer: r.answer, citations: r.citations }];
        const title = aiAction ? `${aiAction} · ${data.document.title}` : `Hỏi về ${data.document.title}`;
        saveConvToStorage(user?.code ?? "", currentId, title, updated);
        return updated;
      });
      setTimeout(() => chatBottomRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "Lỗi không xác định.");
    } finally {
      setChatLoading(false);
    }
  }

  async function download(assetId: string, name: string) {
    const r = await fetch(`${API_URL}/api/files/${assetId}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return;
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a"); a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  }

  if (error) return (
    <div>
      <PageHeader eyebrow="Trình xem tài liệu" title="Không thể mở tài liệu" description="Bạn cần được chủ sở hữu phê duyệt trước khi xem hoặc tải tài liệu riêng tư." actions={<Link className="btn-secondary" href="/permissions"><ChevronLeft size={15}/>Gửi yêu cầu truy cập</Link>}/>
      <p className="rounded bg-red-50 p-4 text-sm text-red-700">{error}</p>
    </div>
  );

  const presets = [
    { title: "Tóm tắt", icon: <MessageSquareText size={16}/>, prompt: `Tóm tắt ngắn gọn các nội dung chính, ý chính và điểm nổi bật của tài liệu "${data.document.title}" thuộc chủ đề ${data.document.topic}. Trình bày theo dạng gạch đầu dòng.` },
    { title: "Giải thích", icon: <BookOpen size={16}/>, prompt: `Tài liệu "${data.document.title}" là gì? Giải thích mục đích, đối tượng sử dụng, cấu trúc và nội dung chính của tài liệu ${data.document.doc_type} này về chủ đề ${data.document.topic}.` },
    { title: "Trích CLO", icon: <Highlighter size={16}/>, prompt: `Liệt kê toàn bộ Chuẩn đầu ra học phần (CLO), mục tiêu học tập và năng lực đạt được liên quan đến chủ đề "${data.document.topic}" trong kho tri thức. Nếu tài liệu "${data.document.title}" có CLO thì trích từ đó, nếu không thì lấy từ tài liệu liên quan. Đánh số từng CLO rõ ràng.` },
    { title: "FAQ", icon: <FileText size={16}/>, prompt: `Dựa trên nội dung trong kho tri thức về chủ đề "${data.document.topic}" (đặc biệt từ tài liệu "${data.document.title}"), hãy tạo 5 câu hỏi thường gặp (FAQ) kèm câu trả lời chi tiết.` },
    { title: "Dịch", icon: <Languages size={16}/>, prompt: `Dịch tiêu đề, mục tiêu và các điểm nội dung quan trọng của tài liệu "${data.document.title}" từ tiếng Việt sang tiếng Anh.` },
    { title: "Liên quan", icon: <Sparkles size={16}/>, prompt: `Tìm và liệt kê các tài liệu khác trong kho tri thức có nội dung liên quan đến chủ đề "${data.document.topic}" hoặc bổ sung cho tài liệu "${data.document.title}".` },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Trình xem tài liệu"
        title={data.document.title || "Đang tải tài liệu..."}
        description={`${data.document.doc_type} · v${data.document.current_version} · ${data.document.owner_code}`}
        actions={<Link className="btn-secondary" href="/repository"><ChevronLeft size={15}/>Kho tài liệu</Link>}
      />

      {data.access.type === "approved_request" && (
        <p className="mb-4 rounded bg-blue-50 p-3 text-xs text-blue-800">Bạn đang xem tài liệu riêng tư này nhờ yêu cầu truy cập đã được chủ sở hữu phê duyệt.</p>
      )}

      <div className="grid gap-4 xl:grid-cols-[220px_minmax(0,1fr)_280px]">
        {/* Left: Versions */}
        <Panel title="Phiên bản">
          <div className="p-2">
            {data.versions.map(x => (
              <div key={x.id} className="rounded-md px-2 py-2 text-xs">
                <strong>Phiên bản {x.version_no}</strong>
                <span className="muted block">{x.created_by} · {formatDate(x.created_at)}</span>
              </div>
            ))}
          </div>
        </Panel>

        {/* Center: Document info + AI chat */}
        <div className="app-card p-6 md:p-10">
          <div className="mx-auto max-w-3xl">
            <span className={`badge ${data.document.visibility === "public" ? "badge-green" : "badge-amber"}`}>
              {data.document.visibility === "public" ? "Công khai" : "Riêng tư"}
            </span>
            <h2 className="mt-5 text-2xl font-bold">{data.document.title}</h2>
            <p className="muted mt-2 text-sm">{data.document.topic} · {data.document.doc_type}</p>
            <div className="mt-8 grid gap-3 sm:grid-cols-2">
              {[["Chủ sở hữu", data.document.owner_code], ["Thư mục", data.document.folder_path || "Chưa phân loại"], ["Ngày tạo", formatDate(data.document.created_at)], ["Cập nhật", formatDate(data.document.updated_at)]].map(x => (
                <div key={x[0]} className="rounded-lg border border-[var(--border)] p-3">
                  <span className="muted block text-[10px] uppercase font-bold">{x[0]}</span>
                  <strong className="text-xs">{x[1]}</strong>
                </div>
              ))}
            </div>

            <h3 className="section-title mt-8">Tệp gốc</h3>
            <div className="mt-3 space-y-2">
              {data.files.map(x => (
                <div key={x.id} className="flex items-center gap-3 rounded-lg border border-[var(--border)] p-3">
                  <FileText size={17} className="text-blue-600"/>
                  <div className="flex-1">
                    <strong className="block text-xs">{x.original_name}</strong>
                    <span className="muted text-[10px]">v{x.version_no} · {Math.ceil(x.size / 1024)} KB</span>
                  </div>
                  <button className="btn-secondary" onClick={() => download(x.id, x.original_name)}><Download size={14}/>Tải xuống</button>
                </div>
              ))}
              {!data.files.length && <p className="muted text-xs">Tài liệu này chưa có tệp gốc.</p>}
            </div>

            {/* AI Chat section */}
            <div className="mt-8">
              <div className="flex items-center justify-between">
                <h3 className="section-title">{aiAction || "Trợ lý AI"}</h3>
                {aiAction && (
                  <span className="muted text-[10px]">Lưu vào lịch sử trợ lý</span>
                )}
              </div>

              {/* Loading state for first request */}
              {chatLoading && chat.length === 0 && (
                <div className="mt-4 flex items-center gap-2 text-sm text-blue-600">
                  <LoaderCircle size={16} className="animate-spin"/>Đang thực hiện...
                </div>
              )}

              {chatError && <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{chatError}</p>}

              {/* Chat thread */}
              {chat.length > 0 && (
                <div className="mt-4 space-y-6">
                  {chat.map((item, i) => (
                    <div key={i}>
                      {/* User bubble — skip for preset (first message), show for follow-up */}
                      {!item.isPreset && (
                        <div className="mb-3 flex justify-end">
                          <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2 text-sm text-white">
                            {item.question}
                          </div>
                        </div>
                      )}
                      {/* AI answer */}
                      <div className="ai-result">
                        <ReactMarkdown>{item.answer}</ReactMarkdown>
                      </div>
                      {/* Citations — collapsible, shown for all messages */}
                      {item.citations.length > 0 && (
                        <CitationToggle citations={item.citations}/>
                      )}
                    </div>
                  ))}

                  {/* Loading for follow-up */}
                  {chatLoading && chat.length > 0 && (
                    <div className="flex items-center gap-2 text-sm text-blue-500">
                      <LoaderCircle size={14} className="animate-spin"/>Đang trả lời...
                    </div>
                  )}
                  <div ref={chatBottomRef}/>
                </div>
              )}

              {/* Chat input — always visible */}
              <form onSubmit={sendChat} className={`flex gap-2 ${chat.length > 0 ? "mt-6 border-t border-[var(--border)] pt-5" : "mt-4"}`}>
                <input
                  className="field"
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  placeholder={chat.length > 0 ? "Hỏi thêm về tài liệu này..." : "Nhập câu hỏi về tài liệu này hoặc chọn chức năng bên phải..."}
                  disabled={chatLoading}
                />
                <button type="submit" disabled={chatLoading || !chatInput.trim()} className="btn-primary px-4 disabled:opacity-50">
                  <Send size={15}/>
                </button>
              </form>
            </div>
          </div>
        </div>

        {/* Right: AI action buttons only */}
        <Panel title="Trợ lý AI">
          <div className="p-3">
            <div className="rounded-xl bg-gradient-to-br from-blue-700 to-indigo-800 p-4 text-white">
              <Sparkles size={18}/>
              <strong className="mt-3 block text-sm">Thông tin nguồn gốc</strong>
              <p className="mt-1 text-[11px] text-blue-100">{data.sync_history.length} lần đồng bộ được ghi nhận.</p>
            </div>
            <p className="muted mt-4 mb-2 text-[10px] uppercase font-bold">Chọn chức năng</p>
            <div className="grid grid-cols-2 gap-2">
              {presets.map(x => (
                <button
                  key={x.title}
                  disabled={chatLoading}
                  onClick={() => askAI(x.title, x.prompt)}
                  className={`btn-secondary flex-col py-3 disabled:opacity-50 ${aiAction === x.title ? "ring-2 ring-blue-500" : ""}`}
                >
                  {x.icon}
                  <span className="text-[10px]">{x.title}</span>
                </button>
              ))}
            </div>
            <p className="muted mt-4 text-[10px] text-center">Cuộc trò chuyện sẽ được lưu vào lịch sử Trợ lý AI</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
