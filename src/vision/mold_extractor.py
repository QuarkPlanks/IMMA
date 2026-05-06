"""
src/vision/mold_extractor.py
─────────────────────────────
Multimodal image analysis for mold engineering drawings.
Given a mold design image (PNG/JPG/PDF screenshot), ask a vision-capable LLM
to extract key dimensional parameters as structured JSON.

The extracted dict is merged into the app's global mold geometry context.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional
from io import BytesIO

from PIL import Image

import sys
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
from config import VISION_API_KEY, VISION_BASE_URL, VISION_MODEL

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Image encoding
# ─────────────────────────────────────────────────────────────────────────────

MAX_SIDE_PX = 1600   # resize if larger to save tokens

def encode_image(image_bytes: bytes, fmt: str = "PNG") -> str:
    """Resize if needed, then base64-encode for the vision API."""
    img = Image.open(BytesIO(image_bytes))
    # Resize while keeping aspect ratio
    w, h = img.size
    if max(w, h) > MAX_SIDE_PX:
        scale = MAX_SIDE_PX / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Vision LLM call
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an expert mold designer analyzing an engineering drawing of an injection mold or molded part.

Please extract all dimensional information you can find and return it as a JSON object with these fields (omit any field not visible or inferable):

{
  "part_geometry":        "plate" | "disc" | "box" | "custom",
  "wall_thickness_mm":    number,
  "part_length_mm":       number,
  "part_width_mm":        number,
  "part_height_mm":       number,
  "runner_length_mm":     number,
  "runner_diameter_mm":   number,
  "gate_type":            "edge" | "pin" | "fan" | "hot" | "submarine" | "unknown",
  "n_cavities":           integer,
  "machine_clamp_kN":     number,
  "draft_angle_deg":      number,
  "rib_thickness_mm":     number,
  "notes":                "any other observations about the mold design"
}

Focus on numerical dimensions visible in the drawing (look for dimension lines, arrows, numbers with mm/cm units).
Return ONLY the JSON object, no explanation."""


def extract_mold_dimensions(image_bytes: bytes, extra_text: str = "") -> dict:
    """
    Send a mold drawing image to the vision LLM and extract dimensions.

    Parameters
    ----------
    image_bytes : bytes
        Raw image data (JPEG or PNG).
    extra_text : str
        Any additional text description the user typed about the mold.

    Returns
    -------
    dict with extracted dimensions (keys match SimulationInput fields).
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL)

        b64 = encode_image(image_bytes)
        prompt = EXTRACTION_PROMPT
        if extra_text.strip():
            prompt += f"\n\nAdditional context from the user:\n{extra_text}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=messages,
            temperature=0,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()

        # Strip markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]

        extracted = json.loads(raw)
        log.info("Vision extraction OK: %s", extracted)
        return extracted

    except json.JSONDecodeError as e:
        log.warning("Vision LLM returned non-JSON: %s", e)
        return {"notes": "图像分析失败：模型返回了非结构化文本，请手动输入尺寸参数。"}
    except Exception as e:
        log.warning("Vision extraction failed: %s", e)
        return {"notes": f"图像分析失败：{e}。请手动输入尺寸参数。"}


DESCRIPTION_PROMPT = """你是一位经验丰富的注塑模具工程师。请仔细分析这张模具图片（可能是模具图纸、制品图或实物照片），
用中文撰写一份详细的模具特点描述，供另一个AI模型用于推荐注塑工艺参数。

请重点描述以下方面（如图片中可见）：
1. 制品整体形状与复杂程度（平板件/壳体/管状/异形件等）
2. 壁厚分布（均匀/差异大）与最薄/最厚处估计
3. 是否有深骨位、柱位、卡扣、侧孔或复杂内部结构
4. 浇口类型与位置（如可见）
5. 分型面位置与特殊结构（如侧抽芯、斜顶）
6. 对注塑工艺的潜在影响（例如：壁厚差大，保压时间需延长；深骨位排气要求高等）

请用简洁、专业的技术语言描述，无需重复图片中的文字标注。"""


def describe_mold_for_agent(image_bytes: bytes, extra_text: str = "") -> str:
    """
    Call Vision LLM to generate a detailed Chinese mold description.
    This description is injected into the main (text) LLM's system prompt
    so it can account for mold geometry when recommending process parameters.

    Returns a Chinese string description, or an empty string on failure.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL)

        b64 = encode_image(image_bytes)
        prompt = DESCRIPTION_PROMPT
        if extra_text.strip():
            prompt += f"\n\n用户补充说明：{extra_text}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=messages,
            temperature=0.2,
            max_tokens=800,
        )
        description = resp.choices[0].message.content.strip()
        log.info("Mold description generated (%d chars)", len(description))
        return description

    except Exception as e:
        log.warning("Mold description generation failed: %s", e)
        return ""


def merge_with_defaults(extracted: dict, current_params: dict) -> dict:
    """
    Merge extracted dimensions into existing parameter dict.
    Extracted values only overwrite if they are non-None.
    """
    field_map = {
        "wall_thickness_mm": "wall_thickness_mm",
        "part_length_mm":    "part_length_mm",
        "part_width_mm":     "part_width_mm",
        "runner_length_mm":  "runner_length_mm",
        "runner_diameter_mm":"runner_diameter_mm",
        "n_cavities":        "n_cavities",
        "machine_clamp_kN":  "machine_clamp_kN",
        "part_geometry":     "part_geometry",
    }
    result = dict(current_params)
    for ext_key, param_key in field_map.items():
        val = extracted.get(ext_key)
        if val is not None:
            result[param_key] = val
    if "notes" in extracted:
        result["vision_notes"] = extracted["notes"]
    return result
