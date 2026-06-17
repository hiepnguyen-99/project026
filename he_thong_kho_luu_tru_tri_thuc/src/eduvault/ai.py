from __future__ import annotations

import json
import hashlib
import base64
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


def load_env_file() -> None:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


class AIProvider:
    """OpenAI-ready AI layer with a deterministic local fallback."""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    @property
    def mode(self) -> str:
        return "openai" if self.api_key else "local"

    def status(self) -> dict:
        return {
            "provider": self.mode, "model": self.model if self.api_key else "local-fallback",
            "embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small") if self.api_key else "local-hash-vector",
            "configured": bool(self.api_key),
        }

    def _response(self, instructions: str, prompt: str) -> str:
        body = json.dumps({"model": self.model, "instructions": instructions, "input": prompt}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/responses", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"OpenAI API không khả dụng: {exc}") from exc
        if data.get("output_text"):
            return data["output_text"]
        return "\n".join(
            content.get("text", "")
            for item in data.get("output", [])
            for content in item.get("content", [])
            if content.get("type") == "output_text"
        )

    def ocr_images(self, images: list[bytes]) -> str:
        if not self.api_key or not images:
            return ""
        content = [{"type": "input_text", "text": "Trích xuất nguyên văn toàn bộ chữ trong các trang tài liệu này. Giữ thứ tự đọc và xuống dòng hợp lý. Chỉ trả nội dung tài liệu."}]
        content.extend(
            {"type": "input_image", "image_url": f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}"}
            for image in images[:10]
        )
        body = json.dumps(
            {"model": self.model, "instructions": "Bạn là hệ thống OCR tài liệu tiếng Việt chính xác.", "input": [{"role": "user", "content": content}]},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/responses", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("output_text"):
                return data["output_text"]
            return "\n".join(
                item.get("text", "")
                for output in data.get("output", [])
                for item in output.get("content", [])
                if item.get("type") == "output_text"
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return ""

    def metadata(self, filename: str, content: str, fallback: dict, instructions: str | None = None) -> dict:
        if not self.api_key:
            return fallback
        try:
            raw = self._response(
                instructions or "Phân loại tài liệu học thuật tiếng Việt. Chỉ trả JSON hợp lệ, không markdown.",
                f"Tên file: {filename}\nNội dung:\n{content[:12000]}\nTrả JSON gồm title, topic, doc_type, summary, keywords.",
            )
            result = json.loads(re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip())
            return {**fallback, **{key: result[key] for key in ("title", "topic", "doc_type", "summary", "keywords") if key in result}}
        except (RuntimeError, json.JSONDecodeError):
            return fallback

    def policy_tree(self, content: str, fallback: dict) -> dict:
        if not self.api_key or not content.strip():
            return fallback
        instructions = """
Ban la bo parser Policy cho he thong EduVault. Chi tra JSON hop le, khong markdown.
Schema bat buoc:
{
  "faculty": {"name": "ten khoa", "code": "ma khoa neu co"},
  "specializations": [
    {
      "name": "ten nhom chuyen mon",
      "description": "",
      "courses": [
        {
          "name": "ten hoc phan",
          "code": "ma hoc phan neu co",
          "description": "",
          "standard_folders": [
            "De cuong mon hoc",
            "Bai giang",
            "Slide",
            "Lab",
            "Bai tap",
            "De thi",
            "Dap an",
            "Tai lieu tham khảo"
          ]
        }
      ]
    }
  ]
}
Khong tao node rong. Khong dat ten node la "Thu muc". Khong tra id ky thuat.
Neu policy chi co hoc phan ma khong noi ro nhom chuyen mon, hay gom theo nhom chuyen mon gan nhat trong van ban.
"""
        try:
            raw = self._response(instructions, f"Noi dung policy:\n{content[:20000]}")
            cleaned = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()
            return {**fallback, **json.loads(cleaned)}
        except (RuntimeError, json.JSONDecodeError):
            return fallback

    def answer(self, question: str, contexts: list[dict], fallback: str, instructions: str | None = None) -> str:
        if not self.api_key or not contexts:
            return fallback
        context = "\n\n".join(f"[{item['title']}]\n{item['content'][:6000]}" for item in contexts)
        experience_instructions = """
Bạn là trợ lý tri thức thân thiện đang trò chuyện trực tiếp với người dùng.
- Không viết như báo cáo kỹ thuật và không mở đầu bằng "Nguồn tài liệu", "Tóm tắt" hoặc "Kết quả".
- Dùng câu ngắn, mỗi đoạn tối đa 2-3 dòng; chia thành các khối dễ quét mắt.
- Dùng markdown và emoji nhẹ. Chỉ dùng bullet ngắn, không tạo danh sách dài liên tục.
- Highlight ý quan trọng bằng **chữ đậm**.
- Với tài liệu dài, ưu tiên tổng quan, chủ đề chính, nội dung cần chú ý và gợi ý học tập.
- Không viết phần nguồn trong câu trả lời; ứng dụng sẽ hiển thị nguồn riêng ở cuối.
- Luôn kết thúc bằng mục "### Bạn có thể hỏi tiếp" với 3-4 câu hỏi gợi ý ngắn.
"""
        try:
            return self._response(
                f"{experience_instructions}\nChỉ dựa trên ngữ cảnh được cung cấp và không tiết lộ dữ liệu ngoài ngữ cảnh.\nHướng dẫn bổ sung của quản trị viên: {instructions or 'Không có.'}",
                f"Ngữ cảnh:\n{context}\n\nCâu hỏi của người dùng: {question}",
            )
        except RuntimeError:
            return fallback

    def embed(self, text: str, force_local: bool = False) -> list[float]:
        if self.api_key and not force_local:
            model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            body = json.dumps({"model": model, "input": text[:24000]}, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url}/embeddings", data=body, method="POST",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    return json.loads(response.read().decode("utf-8"))["data"][0]["embedding"]
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
                pass
        vector = [0.0] * 128
        for word in re.findall(r"\w+", text.lower(), re.UNICODE):
            index = int.from_bytes(hashlib.sha256(word.encode("utf-8")).digest()[:4], "big") % len(vector)
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


ai_provider = AIProvider()
