"use client";

import Link from "next/link";
import { Fragment, ReactNode, useState } from "react";
import { Bot, FileText, LoaderCircle, MessageSquare, Plus, Send, Sparkles } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { API_URL } from "@/lib/api";
import { PageHeader, Panel } from "@/components/ui";

type Citation = { id: string; title: string; topic: string; version: number; visibility: string };
type Answer = { answer: string; citations: Citation[]; scope: string };
type Conversation = { question: string; result: Answer; status?: string; streaming?: boolean };
type StreamEvent =
  | { type: "status"; message: string }
  | { type: "delta"; text: string }
  | { type: "complete"; citations: Citation[]; scope: string }
  | { type: "error"; message: string };

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
    if (!line) {
      flushBullets();
      return;
    }
    if (line.startsWith("- ") || line.startsWith("• ")) {
      bullets.push(line.slice(2));
      return;
    }
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

function Sources({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return <div className="mt-5 border-t border-[var(--border)] pt-4">
    <p className="mb-3 flex items-center gap-2 text-xs font-bold"><FileText className="text-blue-600" size={15}/>📄 Nguồn tham khảo</p>
    <div className="grid gap-2 sm:grid-cols-2">{citations.map(item => <Link href={`/documents/${item.id}`} key={item.id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3 transition hover:border-blue-300 hover:bg-blue-50/40">
      <strong className="block text-xs">{item.title}</strong>
      <span className="muted mt-1 block text-[10px]">{item.topic} · phiên bản {item.version}</span>
    </Link>)}</div>
  </div>;
}

export default function Assistant() {
  const { token } = useAuth();
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function updateConversation(index: number, update: (item: Conversation) => Conversation) {
    setHistory(items => items.map((item, itemIndex) => itemIndex === index ? update(item) : item));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const submittedQuestion = question.trim();
    if (!submittedQuestion || loading) return;
    const conversationIndex = history.length;
    setHistory(items => [...items, {
      question: submittedQuestion,
      result: { answer: "", citations: [], scope: "public_or_owned" },
      status: "Đang kết nối với trợ lý...",
      streaming: true,
    }]);
    setQuestion("");
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/search/stream`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ question: submittedQuestion }),
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
          const streamEvent = JSON.parse(line) as StreamEvent;
          if (streamEvent.type === "status") {
            updateConversation(conversationIndex, item => ({ ...item, status: streamEvent.message }));
          } else if (streamEvent.type === "delta") {
            updateConversation(conversationIndex, item => ({
              ...item,
              status: "",
              result: { ...item.result, answer: item.result.answer + streamEvent.text },
            }));
            await new Promise(resolve => setTimeout(resolve, 18));
          } else if (streamEvent.type === "complete") {
            updateConversation(conversationIndex, item => ({
              ...item,
              streaming: false,
              status: "",
              result: { ...item.result, citations: streamEvent.citations, scope: streamEvent.scope },
            }));
          } else if (streamEvent.type === "error") {
            throw new Error(streamEvent.message);
          }
        }
        if (done) break;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể hỏi trợ lý.");
      updateConversation(conversationIndex, item => ({
        ...item,
        streaming: false,
        status: "",
        result: { ...item.result, answer: item.result.answer || (err instanceof Error ? err.message : "Không thể hỏi trợ lý.") },
      }));
    } finally {
      setLoading(false);
    }
  }

  return <div>
    <PageHeader eyebrow="Trợ lý tri thức AI" title="Hỏi đáp trên kho tri thức" description="Hỏi tự nhiên như đang trao đổi với một trợ lý hiểu tài liệu của bạn." actions={<button className="btn-primary" onClick={() => setHistory([])}><Plus size={15}/>Cuộc hội thoại mới</button>}/>
    <div className="grid min-h-[680px] gap-4 xl:grid-cols-[240px_minmax(0,1fr)]">
      <Panel title="Lịch sử"><div className="p-2">{history.map((item, index) => <button key={index} className="flex w-full gap-2 rounded-lg p-2.5 text-left text-xs hover:bg-[var(--soft)]"><MessageSquare size={14}/>{item.question}</button>)}{!history.length && <p className="muted p-3 text-xs">Chưa có câu hỏi.</p>}</div></Panel>
      <Panel title="Trợ lý tri thức" description="Câu trả lời chỉ dùng những tài liệu bạn được phép xem">
        <div className="flex h-[610px] flex-col p-4">
          <div className="flex-1 space-y-5 overflow-y-auto pr-1">
            <div className="max-w-[88%] rounded-xl rounded-tl-sm bg-[var(--soft)] p-4 text-sm">
              <div className="mb-2 flex items-center gap-2 font-bold text-blue-600"><Bot size={16}/>EduVault AI</div>
              Chào bạn, mình có thể giúp **tóm tắt tài liệu**, giải thích nội dung khó hoặc gợi ý cách ôn tập. Bạn muốn tìm hiểu điều gì?
            </div>
            {history.map((item, index) => <div key={index} className="space-y-4">
              <div className="ml-auto max-w-[80%] rounded-xl rounded-tr-sm bg-blue-600 p-4 text-sm text-white">{item.question}</div>
              <div className="max-w-[95%] rounded-xl rounded-tl-sm bg-[var(--soft)] p-5 text-sm">
                <div className="mb-4 flex items-center gap-2 font-bold text-blue-600"><Sparkles size={16}/>{item.streaming ? item.status || "Đang trả lời..." : "Mình đã tìm thấy nội dung phù hợp"}</div>
                {item.result.answer ? <div><FriendlyAnswer answer={item.result.answer}/>{item.streaming && <span className="ml-1 inline-block h-4 w-1.5 animate-pulse bg-blue-600 align-middle"/>}</div> : <div className="flex items-center gap-2 text-xs text-[var(--muted)]"><LoaderCircle className="animate-spin" size={14}/>{item.status}</div>}
                {!item.streaming && <Sources citations={item.result.citations}/>}
              </div>
            </div>)}
          </div>
          {error && <p className="mb-2 rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
          <form onSubmit={submit} className="mt-4 flex gap-2">
            <input className="field" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Ví dụ: Giải thích các bước xây dựng hệ thống RAG..."/>
            <button disabled={loading} className="btn-primary" aria-label="Gửi">{loading ? <LoaderCircle className="animate-spin" size={16}/> : <Send size={16}/>}</button>
          </form>
        </div>
      </Panel>
    </div>
  </div>;
}
