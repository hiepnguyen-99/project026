"use client";

import Link from "next/link";
import { Fragment, ReactNode, useEffect, useRef, useState } from "react";
import { Bot, ChevronDown, Download, ExternalLink, FileText, LoaderCircle, MessageSquare, Plus, Send, Sparkles, Trash2, X } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { API_URL } from "@/lib/api";
import { PageHeader, Panel } from "@/components/ui";

type Citation = { id: string; title: string; topic: string; version: number; visibility: string };
type Answer = { answer: string; citations: Citation[]; scope: string };
type MessageItem = { question: string; result: Answer; status?: string; streaming?: boolean };
type Conversation = { id: string; title: string; messages: MessageItem[]; updatedAt: number };
type StreamEvent =
  | { type: "status"; message: string }
  | { type: "delta"; text: string }
  | { type: "complete"; citations: Citation[]; scope: string }
  | { type: "error"; message: string };

const STORAGE_KEY = "eduvault_conversations";

/** Mỗi tài khoản có lịch sử chat riêng: khóa lưu trữ gắn theo mã giảng viên. */
function convStorageKey(code: string): string {
  return `${STORAGE_KEY}:${code}`;
}

function newConv(): Conversation {
  return { id: crypto.randomUUID(), title: "Cuộc hội thoại mới", messages: [], updatedAt: Date.now() };
}

function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return <>{parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={index}>{part.slice(1, -1)}</em>;
    return <Fragment key={index}>{part}</Fragment>;
  })}</>;
}

function FriendlyAnswer({ answer }: { answer: string }) {
  const lines = answer.split("\n");
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  function flushBullets() {
    if (!bullets.length) return;
    blocks.push(<ul key={`list-${blocks.length}`} className="space-y-2 pl-1">{bullets.map((item, index) => <li key={index} className="flex gap-2"><span className="mt-0.5 text-blue-600">•</span><span><InlineMarkdown text={item}/></span></li>)}</ul>);
    bullets = [];
  }
  lines.forEach((raw, index) => {
    const line = raw.trim();
    if (!line) { flushBullets(); return; }
    if (line.startsWith("- ") || line.startsWith("• ")) { bullets.push(line.slice(2)); return; }
    flushBullets();
    if (line.startsWith("### ")) {
      blocks.push(<h3 key={index} className="pt-3 text-sm font-bold text-[var(--text)]"><InlineMarkdown text={line.slice(4)}/></h3>);
    } else {
      blocks.push(<p key={index} className="leading-6"><InlineMarkdown text={line}/></p>);
    }
  });
  flushBullets();
  return <div className="space-y-3">{blocks}</div>;
}

type DocPreview = { id: string; title: string; content: string; files: { id: string; original_name: string; mime_type: string; size: number }[] };

function DocModal({ doc, token, onClose }: { doc: DocPreview; token: string; onClose: () => void }) {
  async function download(assetId: string, name: string) {
    const r = await fetch(`${API_URL}/api/files/${assetId}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return;
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a"); a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="fixed inset-0 z-[80] bg-slate-950/60 p-4 flex items-center justify-center" onClick={onClose}>
      <div className="app-card w-full max-w-2xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
          <div><p className="eyebrow">Xem nội dung tài liệu</p><h2 className="mt-0.5 text-base font-bold">{doc.title}</h2></div>
          <div className="flex shrink-0 items-center gap-2">
            <Link href={`/documents/${doc.id}`} className="btn-secondary text-xs flex items-center gap-1"><ExternalLink size={13}/>Mở trang chi tiết</Link>
            <button className="icon-btn" onClick={onClose}><X size={17}/></button>
          </div>
        </div>
        {doc.files.length > 0 && (
          <div className="border-b border-[var(--border)] bg-[var(--soft)] px-4 py-3 flex flex-wrap gap-2">
            {doc.files.map(f => <button key={f.id} onClick={() => download(f.id, f.original_name)} className="btn-secondary flex items-center gap-1.5 text-xs"><Download size={13}/>{f.original_name}</button>)}
          </div>
        )}
        <div className="flex-1 overflow-auto p-5">
          {doc.content ? <pre className="whitespace-pre-wrap text-xs leading-relaxed text-[var(--text)]">{doc.content}</pre> : <p className="muted text-xs">Tài liệu này chưa có nội dung văn bản được trích xuất.</p>}
        </div>
      </div>
    </div>
  );
}

function Sources({ citations, onPreview }: { citations: Citation[]; onPreview?: (id: string, title: string) => void }) {
  const [open, setOpen] = useState(false);
  if (!citations.length) return null;
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
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {citations.map(item => (
            <div key={item.id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
              <strong className="block text-xs">{item.title}</strong>
              <span className="muted mt-1 block text-[10px]">{item.topic} · phiên bản {item.version}</span>
              <div className="mt-2 flex gap-2">
                {onPreview && <button onClick={() => onPreview(item.id, item.title)} className="flex items-center gap-1 text-[11px] font-bold text-blue-600 hover:underline"><FileText size={11}/>Xem nội dung</button>}
                {onPreview && <span className="text-[var(--border)]">·</span>}
                <Link href={`/documents/${item.id}`} className="flex items-center gap-1 text-[11px] text-[var(--muted)] hover:text-blue-600"><ExternalLink size={11}/>Chi tiết</Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Assistant() {
  const { token, user } = useAuth();
  const [question, setQuestion] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<DocPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Khóa lưu trữ riêng cho tài khoản đang đăng nhập; rỗng khi chưa có user.
  const storageKey = user ? convStorageKey(user.code) : "";
  // Ghi nhớ lịch sử hiện đang thuộc về tài khoản nào, tránh ghi nhầm khi đổi tài khoản.
  const loadedKey = useRef("");

  useEffect(() => {
    if (!storageKey) return;
    let loaded: Conversation[] = [];
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) loaded = JSON.parse(saved);
    } catch { /* ignore */ }
    if (!loaded.length) loaded = [newConv()];
    setConversations(loaded);
    setActiveId(loaded[0].id);
    loadedKey.current = storageKey;
  }, [storageKey]);

  useEffect(() => {
    // Chỉ lưu khi lịch sử đang hiển thị đúng là của tài khoản hiện tại.
    if (!storageKey || loadedKey.current !== storageKey || !conversations.length) return;
    try {
      // Strip streaming state before saving
      const toSave = conversations.map(c => ({
        ...c,
        messages: c.messages.map(m => ({ ...m, streaming: false, status: undefined })),
      }));
      localStorage.setItem(storageKey, JSON.stringify(toSave.slice(0, 30)));
    } catch { /* ignore */ }
  }, [conversations, storageKey]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeId, conversations]);

  const activeConv = conversations.find(c => c.id === activeId);
  const messages = activeConv?.messages ?? [];

  function updateMessage(convId: string, msgIndex: number, update: (m: MessageItem) => MessageItem) {
    setConversations(prev => prev.map(c => {
      if (c.id !== convId) return c;
      return { ...c, messages: c.messages.map((m, i) => i === msgIndex ? update(m) : m), updatedAt: Date.now() };
    }));
  }

  function createNew() {
    const c = newConv();
    setConversations(prev => [c, ...prev]);
    setActiveId(c.id);
    setError("");
    setQuestion("");
  }

  function deleteConv(id: string) {
    setConversations(prev => {
      const next = prev.filter(c => c.id !== id);
      if (id === activeId) {
        if (next.length) setActiveId(next[0].id);
        else {
          const fresh = newConv();
          setActiveId(fresh.id);
          return [fresh];
        }
      }
      return next;
    });
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const q = question.trim();
    if (!q || loading) return;
    setQuestion("");
    setLoading(true);
    setError("");

    const targetId = activeId;
    let msgIndex = -1;

    setConversations(prev => prev.map(c => {
      if (c.id !== targetId) return c;
      const isFirst = c.messages.length === 0;
      msgIndex = c.messages.length;
      return {
        ...c,
        title: isFirst ? q.slice(0, 60) : c.title,
        messages: [...c.messages, {
          question: q,
          result: { answer: "", citations: [], scope: "public_or_owned" },
          status: "Đang kết nối với trợ lý...",
          streaming: true,
        }],
        updatedAt: Date.now(),
      };
    }));

    try {
      const response = await fetch(`${API_URL}/api/search/stream`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!response.ok || !response.body) throw new Error(`Máy chủ trả về lỗi HTTP ${response.status}.`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = done ? "" : lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line) as StreamEvent;
          if (ev.type === "status") {
            updateMessage(targetId, msgIndex, m => ({ ...m, status: ev.message }));
          } else if (ev.type === "delta") {
            updateMessage(targetId, msgIndex, m => ({
              ...m, status: "",
              result: { ...m.result, answer: m.result.answer + ev.text },
            }));
            await new Promise(r => setTimeout(r, 18));
          } else if (ev.type === "complete") {
            updateMessage(targetId, msgIndex, m => ({
              ...m, streaming: false, status: "",
              result: { ...m.result, citations: ev.citations, scope: ev.scope },
            }));
          } else if (ev.type === "error") {
            throw new Error(ev.message);
          }
        }
        if (done) break;
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Không thể hỏi trợ lý.";
      setError(msg);
      if (msgIndex >= 0) {
        updateMessage(targetId, msgIndex, m => ({
          ...m, streaming: false, status: "",
          result: { ...m.result, answer: m.result.answer || msg },
        }));
      }
    } finally {
      setLoading(false);
    }
  }

  async function openPreview(id: string, title: string) {
    setPreviewLoading(true);
    try {
      const [detail, provenance] = await Promise.all([
        fetch(`${API_URL}/api/documents/${id}`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()),
        fetch(`${API_URL}/api/documents/${id}/provenance`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()),
      ]);
      setPreview({ id, title, content: detail.content, files: provenance.files || [] });
    } catch {
      setPreview({ id, title, content: "", files: [] });
    } finally {
      setPreviewLoading(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Trợ lý tri thức AI"
        title="Hỏi đáp trên kho tri thức"
        description="Hỏi tự nhiên như đang trao đổi với một trợ lý hiểu tài liệu của bạn."
        actions={<button className="btn-primary" onClick={createNew}><Plus size={15}/>Cuộc hội thoại mới</button>}
      />
      <div className="grid min-h-[680px] gap-4 xl:grid-cols-[240px_minmax(0,1fr)]">
        <Panel title={`Lịch sử (${conversations.length})`}>
          <div className="p-2 max-h-[70vh] overflow-auto space-y-0.5">
            {conversations.map(c => (
              <div key={c.id} className={`group flex items-start gap-1 rounded-lg px-2 py-2 ${c.id === activeId ? "bg-blue-50 dark:bg-blue-950/30" : "hover:bg-[var(--soft)]"}`}>
                <button className="flex min-w-0 flex-1 gap-2 text-left" onClick={() => { setActiveId(c.id); setError(""); }}>
                  <MessageSquare size={14} className={`mt-0.5 shrink-0 ${c.id === activeId ? "text-blue-600" : "text-[var(--muted)]"}`}/>
                  <div className="min-w-0">
                    <span className={`block truncate text-xs font-medium ${c.id === activeId ? "text-blue-700" : ""}`}>{c.title}</span>
                    <span className="muted text-[10px]">{c.messages.length} tin · {new Date(c.updatedAt).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
                  </div>
                </button>
                <button onClick={() => deleteConv(c.id)} className="mt-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-[var(--muted)] hover:text-red-500" title="Xóa">
                  <Trash2 size={13}/>
                </button>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Trợ lý tri thức" description="Câu trả lời chỉ dùng những tài liệu bạn được phép xem">
          <div className="flex h-[610px] flex-col p-4">
            <div className="flex-1 space-y-5 overflow-y-auto pr-1">
              <div className="max-w-[88%] rounded-xl rounded-tl-sm bg-[var(--soft)] p-4 text-sm">
                <div className="mb-2 flex items-center gap-2 font-bold text-blue-600"><Bot size={16}/>EduVault AI</div>
                Chào bạn, mình có thể giúp <strong>tóm tắt tài liệu</strong>, giải thích nội dung khó hoặc gợi ý cách ôn tập. Bạn muốn tìm hiểu điều gì?
              </div>
              {messages.map((item, index) => (
                <div key={index} className="space-y-4">
                  <div className="ml-auto max-w-[80%] rounded-xl rounded-tr-sm bg-blue-600 p-4 text-sm text-white">{item.question}</div>
                  <div className="max-w-[95%] rounded-xl rounded-tl-sm bg-[var(--soft)] p-5 text-sm">
                    <div className="mb-4 flex items-center gap-2 font-bold text-blue-600">
                      <Sparkles size={16}/>
                      {item.streaming ? item.status || "Đang trả lời..." : "Mình đã tìm thấy nội dung phù hợp"}
                    </div>
                    {item.result.answer
                      ? <div><FriendlyAnswer answer={item.result.answer}/>{item.streaming && <span className="ml-1 inline-block h-4 w-1.5 animate-pulse bg-blue-600 align-middle"/>}</div>
                      : <div className="flex items-center gap-2 text-xs text-[var(--muted)]"><LoaderCircle className="animate-spin" size={14}/>{item.status}</div>
                    }
                    {!item.streaming && <Sources citations={item.result.citations} onPreview={openPreview}/>}
                  </div>
                </div>
              ))}
              <div ref={bottomRef}/>
            </div>
            {previewLoading && (
              <div className="mb-2 flex items-center gap-2 rounded bg-blue-50 p-2 text-xs text-blue-700">
                <LoaderCircle size={13} className="animate-spin"/>Đang tải nội dung tài liệu...
              </div>
            )}
            {error && <p className="mb-2 rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
            <form onSubmit={submit} className="mt-4 flex gap-2">
              <input
                className="field"
                value={question}
                onChange={e => setQuestion(e.target.value)}
                placeholder="Ví dụ: Giải thích các bước xây dựng hệ thống RAG..."
              />
              <button disabled={loading} className="btn-primary" aria-label="Gửi">
                {loading ? <LoaderCircle className="animate-spin" size={16}/> : <Send size={16}/>}
              </button>
            </form>
          </div>
        </Panel>
      </div>

      {preview && <DocModal doc={preview} token={token || ""} onClose={() => setPreview(null)}/>}
    </div>
  );
}
