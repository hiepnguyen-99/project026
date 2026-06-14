export default function Loading() {
  return (
    <div aria-label="Đang tải" className="animate-pulse">
      <div className="mb-6 h-8 w-64 rounded bg-[var(--border)]" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[1, 2, 3, 4].map((item) => <div key={item} className="app-card h-32 bg-[var(--card)]" />)}
      </div>
      <div className="app-card mt-5 h-96 bg-[var(--card)]" />
    </div>
  );
}
