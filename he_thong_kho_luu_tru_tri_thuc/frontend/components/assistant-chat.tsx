"use client";

import Link from "next/link";
import { Fragment, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Bot, ChevronDown, Download, ExternalLink, FileText, Flag, LoaderCircle, MessageSquare, Plus, Send, Sparkles, ThumbsDown, ThumbsUp, Trash2, X } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { API_URL } from "@/lib/api";

type Citation = { id: string; title: string; topic: string; version: number; visibility: string; chunk?: string; score?: number };
type Verification = { status: string; message: string };
type Answer = { answer: string; citations: Citation[]; scope: string; trace_id?: string; intent?: string; rewritten_query?: string; verification?: Verification };
type FeedbackRating = "up" | "wrong_source" | "missing_document";
type MessageItem = { question: string; result: Answer; status?: string; streaming?: boolean; feedback?: FeedbackRating };
type Conversation = { id: string; title: string; messages: MessageItem[]; updatedAt: number };
type StreamEvent =
  | { type: "status"; message: string }
  | { type: "delta"; text: string }
  | { type: "complete"; citations: Citation[]; scope: string; trace_id?: string; intent?: string; rewritten_query?: string; verification?: Verification }
  | { type: "error"; message: string };

type AssistantContext = {
  title?: string;
  lines?: string[];
};

type AssistantChatProps = {
  variant?: "page" | "panel";
  context?: AssistantContext;
  onClose?: () => void;
  className?: string;
};

type DocPreview = { id: string; title: string; content: string; files: { id: string; original_name: string; mime_type: string; size: number }[] };

const STORAGE_KEY = "eduvault_conversations";

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

function buildContextQuestion(question: string, context?: AssistantContext) {
  const lines = (context?.lines || []).map(line => line.trim()).filter(Boolean);
  if (!lines.length) return question;
  return `Ngữ cảnh trang hiện tại: ${context?.title || "EduVault"}\n${lines.join("\n")}\n\nCâu hỏi của người dùng: ${question}`;
}

function Sources({ citations, onPreview }: { citations: Citation[]; onPreview?: (id: string, title: string) => void }) {
  const [open, setOpen] = useState(false);
  if (!citations.length) return null;
  return <div className="mt-4 border-t border-[var(--border)] pt-3">
    <button onClick={() => setOpen(value => !value)} className="flex items-center gap-1.5 text-[11px] text-[var(--muted)] transition-colors hover:text-blue-600">
      <FileText size={12}/>
      Nguồn tham khảo ({citations.length})
      <ChevronDown size={12} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}/>
    </button>
    {open && <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {citations.map(item => <div key={item.id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
        <strong className="block text-xs">{item.title}</strong>
        <span className="muted mt-1 block text-[10px]">{item.topic} · phiên bản {item.version}</span>
        <div className="mt-2 flex gap-2">
          {onPreview && <button onClick={() => onPreview(item.id, item.title)} className="flex items-center gap-1 text-[11px] font-bold text-blue-600 hover:underline"><FileText size={11}/>Xem nội dung</button>}
          {onPreview && <span className="text-[var(--border)]">·</span>}
          <Link href={`/documents/${item.id}#pdf`} className="flex items-center gap-1 text-[11px] text-[var(--muted)] hover:text-blue-600"><ExternalLink size={11}/>Chi tiết</Link>
        </div>
      </div>)}
    </div>}
  </div>;
}

function FeedbackControls({ value, disabled, onSend }: { value?: FeedbackRating; disabled?: boolean; onSend: (rating: FeedbackRating) => void }) {
  const options: { rating: FeedbackRating; label: string; icon: ReactNode }[] = [
    { rating: "up", label: "Hữu ích", icon: <ThumbsUp size={12}/> },
    { rating: "wrong_source", label: "Sai nguồn", icon: <ThumbsDown size={12}/> },
    { rating: "missing_document", label: "Thiếu tài liệu", icon: <Flag size={12}/> },
  ];
  return <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
    <span className="text-[11px] font-semibold text-[var(--muted)]">Phản hồi</span>
    {options.map(item => <button key={item.rating} type="button" disabled={disabled || !!value} onClick={() => onSend(item.rating)} className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-[11px] font-semibold transition-colors ${value === item.rating ? "border-blue-200 bg-blue-50 text-blue-700" : "border-[var(--border)] bg-[var(--card)] text-[var(--muted)] hover:border-blue-200 hover:text-blue-600"} disabled:cursor-default disabled:opacity-70`}>
      {item.icon}
      {value === item.rating ? "Đã ghi nhận" : item.label}
    </button>)}
  </div>;
}

function DocModal({ doc, token, onClose }: { doc: DocPreview; token: string; onClose: () => void }) {
  async function download(assetId: string, name: string) {
    const response = await fetch(`${API_URL}/api/files/${assetId}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/60 p-4" onClick={onClose}>
    <div className="app-card flex max-h-[85vh] w-full max-w-2xl flex-col" onClick={event => event.stopPropagation()}>
      <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
        <div><p className="eyebrow">Xem nội dung tài liệu</p><h2 className="mt-0.5 text-base font-bold">{doc.title}</h2></div>
        <div className="flex shrink-0 items-center gap-2">
          <Link href={`/documents/${doc.id}#pdf`} className="btn-secondary flex items-center gap-1 text-xs"><ExternalLink size={13}/>Mở trang chi tiết</Link>
          <button className="icon-btn" onClick={onClose} aria-label="Đóng"><X size={17}/></button>
        </div>
      </div>
      {doc.files.length > 0 && <div className="flex flex-wrap gap-2 border-b border-[var(--border)] bg-[var(--soft)] px-4 py-3">
        {doc.files.map(file => <button key={file.id} onClick={() => download(file.id, file.original_name)} className="btn-secondary flex items-center gap-1.5 text-xs"><Download size={13}/>{file.original_name}</button>)}
      </div>}
      <div className="flex-1 overflow-auto p-5">
        {doc.content ? <pre className="whitespace-pre-wrap text-xs leading-relaxed text-[var(--text)]">{doc.content}</pre> : <p className="muted text-xs">Tài liệu này chưa có nội dung văn bản được trích xuất.</p>}
      </div>
    </div>
  </div>;
}

export function AssistantChat({ variant = "page", context, onClose, className = "" }: AssistantChatProps) {
  const { token, user } = useAuth();
  const [question, setQuestion] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<DocPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const loadedKey = useRef("");
  const storageKey = user ? convStorageKey(user.code) : "";
  const activeConv = conversations.find(c => c.id === activeId);
  const messages = activeConv?.messages ?? [];
  const isPanel = variant === "panel";
  const contextLines = useMemo(() => (context?.lines || []).filter(Boolean), [context?.lines]);

  useEffect(() => {
    if (!storageKey) return;
    let loaded: Conversation[] = [];
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) loaded = JSON.parse(saved);
    } catch { /* ignore invalid history */ }
    if (!loaded.length) loaded = [newConv()];
    setConversations(loaded);
    setActiveId(loaded[0].id);
    loadedKey.current = storageKey;
  }, [storageKey]);

  useEffect(() => {
    if (!storageKey || loadedKey.current !== storageKey || !conversations.length) return;
    try {
      const toSave = conversations.map(c => ({
        ...c,
        messages: c.messages.map(m => ({ ...m, streaming: false, status: undefined })),
      }));
      localStorage.setItem(storageKey, JSON.stringify(toSave.slice(0, 30)));
    } catch { /* ignore quota errors */ }
  }, [conversations, storageKey]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeId, conversations]);

  function updateMessage(convId: string, msgIndex: number, update: (m: MessageItem) => MessageItem) {
    setConversations(prev => prev.map(c => c.id === convId ? { ...c, messages: c.messages.map((m, i) => i === msgIndex ? update(m) : m), updatedAt: Date.now() } : c));
  }

  function createNew() {
    const fresh = newConv();
    setConversations(prev => [fresh, ...prev]);
    setActiveId(fresh.id);
    setError("");
    setQuestion("");
  }

  function clearActive() {
    setConversations(prev => prev.map(c => c.id === activeId ? { ...c, title: "Cuộc hội thoại mới", messages: [], updatedAt: Date.now() } : c));
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

  async function sendFeedback(messageIndex: number, rating: FeedbackRating) {
    const item = messages[messageIndex];
    if (!item?.result.trace_id || item.feedback || !token) return;
    const reasonByRating: Record<FeedbackRating, string> = { up: "helpful", wrong_source: "wrong_source", missing_document: "missing_document" };
    try {
      const response = await fetch(`${API_URL}/api/search/feedback`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ trace_id: item.result.trace_id, rating, reason: reasonByRating[rating], detail: item.question }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      updateMessage(activeId, messageIndex, m => ({ ...m, feedback: rating }));
    } catch {
      setError("Không thể ghi nhận phản hồi lúc này.");
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const displayQuestion = question.trim();
    if (!displayQuestion || loading || !token) return;
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
        title: isFirst ? displayQuestion.slice(0, 60) : c.title,
        messages: [...c.messages, {
          question: displayQuestion,
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
        body: JSON.stringify({ question: buildContextQuestion(displayQuestion, context) }),
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
          const event = JSON.parse(line) as StreamEvent;
          if (event.type === "status") {
            updateMessage(targetId, msgIndex, m => ({ ...m, status: event.message }));
          } else if (event.type === "delta") {
            updateMessage(targetId, msgIndex, m => ({ ...m, status: "", result: { ...m.result, answer: m.result.answer + event.text } }));
            await new Promise(resolve => setTimeout(resolve, 18));
          } else if (event.type === "complete") {
            updateMessage(targetId, msgIndex, m => ({
              ...m,
              streaming: false,
              status: "",
              result: { ...m.result, citations: event.citations, scope: event.scope, trace_id: event.trace_id, intent: event.intent, rewritten_query: event.rewritten_query, verification: event.verification },
            }));
          } else if (event.type === "error") {
            throw new Error(event.message);
          }
        }
        if (done) break;
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Không thể hỏi trợ lý.";
      setError(msg);
      if (msgIndex >= 0) updateMessage(targetId, msgIndex, m => ({ ...m, streaming: false, status: "", result: { ...m.result, answer: m.result.answer || msg } }));
    } finally {
      setLoading(false);
    }
  }

  async function openPreview(id: string, title: string) {
    if (!token) return;
    setPreviewLoading(true);
    try {
      const [detail, provenance] = await Promise.all([
        fetch(`${API_URL}/api/documents/${id}`, { headers: { Authorization: `Bearer ${token}` } }).then(response => response.json()),
        fetch(`${API_URL}/api/documents/${id}/provenance`, { headers: { Authorization: `Bearer ${token}` } }).then(response => response.json()),
      ]);
      setPreview({ id, title, content: detail.content, files: provenance.files || [] });
    } catch {
      setPreview({ id, title, content: "", files: [] });
    } finally {
      setPreviewLoading(false);
    }
  }

  return <div className={`flex min-h-0 flex-col overflow-hidden ${isPanel ? "h-full bg-[var(--card)]" : "app-card min-h-[680px]"} ${className}`}>
    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2 font-bold"><Bot className="text-blue-600" size={17}/>Trợ lý AI EduVault</div>
        <p className="muted mt-0.5 truncate text-[11px]">{context?.title || "Hỏi đáp trên kho tri thức được phép truy cập"}</p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button className="icon-btn h-8 w-8" title="Cuộc hội thoại mới" aria-label="Cuộc hội thoại mới" onClick={createNew}><Plus size={14}/></button>
        <button className="icon-btn h-8 w-8" title="Xóa nội dung chat" aria-label="Xóa nội dung chat" onClick={clearActive}><Trash2 size={14}/></button>
        {onClose && <button className="icon-btn h-8 w-8" title="Đóng trợ lý" aria-label="Đóng trợ lý" onClick={onClose}><X size={15}/></button>}
      </div>
    </div>

    {contextLines.length > 0 && <div className="shrink-0 border-b border-[var(--border)] bg-blue-50/60 px-4 py-2 text-[11px] text-blue-900">
      <strong className="block">Ngữ cảnh hiện tại</strong>
      <p className="mt-1 line-clamp-2">{contextLines.join(" · ")}</p>
    </div>}

    <div className={`min-h-0 flex-1 ${isPanel ? "flex flex-col" : "grid xl:grid-cols-[240px_minmax(0,1fr)]"}`}>
      <aside className={`${isPanel ? "max-h-28 shrink-0 border-b" : "border-r"} border-[var(--border)] overflow-auto`}>
        <div className={`${isPanel ? "flex gap-2 overflow-x-auto p-2" : "space-y-0.5 p-2"}`}>
          {conversations.map(c => <div key={c.id} className={`group flex min-w-0 items-start gap-1 rounded-lg px-2 py-2 ${isPanel ? "w-52 shrink-0" : ""} ${c.id === activeId ? "bg-blue-50" : "hover:bg-[var(--soft)]"}`}>
            <button className="flex min-w-0 flex-1 gap-2 text-left" onClick={() => { setActiveId(c.id); setError(""); }}>
              <MessageSquare size={14} className={`mt-0.5 shrink-0 ${c.id === activeId ? "text-blue-600" : "text-[var(--muted)]"}`}/>
              <div className="min-w-0">
                <span className={`block truncate text-xs font-medium ${c.id === activeId ? "text-blue-700" : ""}`}>{c.title}</span>
                <span className="muted text-[10px]">{c.messages.length} tin · {new Date(c.updatedAt).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
              </div>
            </button>
            <button onClick={() => deleteConv(c.id)} className="mt-0.5 shrink-0 text-[var(--muted)] opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100" title="Xóa"><Trash2 size={13}/></button>
          </div>)}
        </div>
      </aside>

      <section className="flex min-h-0 flex-1 flex-col p-4">
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
          <div className="max-w-[88%] rounded-xl rounded-tl-sm bg-[var(--soft)] p-4 text-sm">
            <div className="mb-2 flex items-center gap-2 font-bold text-blue-600"><Bot size={16}/>EduVault AI</div>
            Chào bạn, mình có thể giúp tóm tắt tài liệu, giải thích nội dung hoặc tìm câu trả lời từ kho tri thức bạn được phép xem.
          </div>
          {messages.map((item, index) => <div key={index} className="space-y-4">
            <div className="ml-auto max-w-[82%] rounded-xl rounded-tr-sm bg-blue-600 p-4 text-sm text-white">{item.question}</div>
            <div className="max-w-[95%] rounded-xl rounded-tl-sm bg-[var(--soft)] p-5 text-sm">
              <div className="mb-4 flex items-center gap-2 font-bold text-blue-600">
                <Sparkles size={16}/>
                {item.streaming ? item.status || "Đang trả lời..." : "Mình đã tìm thấy nội dung phù hợp"}
              </div>
              {item.result.answer ? <div><FriendlyAnswer answer={item.result.answer}/>{item.streaming && <span className="ml-1 inline-block h-4 w-1.5 animate-pulse bg-blue-600 align-middle"/>}</div> : <div className="flex items-center gap-2 text-xs text-[var(--muted)]"><LoaderCircle className="animate-spin" size={14}/>{item.status}</div>}
              {!item.streaming && <Sources citations={item.result.citations} onPreview={openPreview}/>}
              {!item.streaming && item.result.trace_id && <FeedbackControls value={item.feedback} onSend={rating => sendFeedback(index, rating)}/>}
            </div>
          </div>)}
          <div ref={bottomRef}/>
        </div>

        {previewLoading && <div className="mb-2 flex items-center gap-2 rounded bg-blue-50 p-2 text-xs text-blue-700"><LoaderCircle size={13} className="animate-spin"/>Đang tải nội dung tài liệu...</div>}
        {error && <p className="mb-2 rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
        <form onSubmit={submit} className="mt-4 flex gap-2">
          <input className="field" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Nhập câu hỏi cho Trợ lý AI EduVault..."/>
          <button disabled={loading || !token} className="btn-primary" aria-label="Gửi">{loading ? <LoaderCircle className="animate-spin" size={16}/> : <Send size={16}/>}</button>
        </form>
      </section>
    </div>

    {preview && <DocModal doc={preview} token={token || ""} onClose={() => setPreview(null)}/>}
  </div>;
}
