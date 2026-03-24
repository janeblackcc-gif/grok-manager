from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FeaturePreset:
    preset_id: str
    title: str
    feature: str
    prompt: str
    model: str
    web_enabled: bool = True
    mode: str = "detailed"
    tags: tuple[str, ...] = field(default_factory=tuple)


PRESETS: list[FeaturePreset] = [
    FeaturePreset(
        preset_id="search-latest-ai",
        title="AI Search / 热点检索",
        feature="search",
        prompt="总结最近值得关注的 AI 编程工具趋势，并给出结构化结论。",
        model="grok-4.20-beta",
        web_enabled=True,
        mode="detailed",
        tags=("safe", "search"),
    ),
    FeaturePreset(
        preset_id="enhance-image",
        title="Prompt Enhance / 生图润色",
        feature="prompt_enhance_image",
        prompt="雨夜街头的赛博朋克少女",
        model="grok-4.20-beta",
        web_enabled=False,
        mode="image",
        tags=("safe", "prompt"),
    ),
    FeaturePreset(
        preset_id="image-basic",
        title="Image / 基础生图",
        feature="image_generation",
        prompt="cinematic portrait of a futuristic traveler, rainy city, reflective neon, highly detailed",
        model="grok-imagine-1.0",
        web_enabled=False,
        mode="image",
        tags=("safe", "image"),
    ),
    FeaturePreset(
        preset_id="image-edit-latest",
        title="Image Edit / 最近一张图微调",
        feature="image_edit",
        prompt="保持主体不变，强化光影层次和金属材质细节。",
        model="grok-imagine-1.0-edit",
        web_enabled=False,
        mode="image_edit",
        tags=("safe", "image_edit"),
    ),
    FeaturePreset(
        preset_id="video-basic",
        title="Video / 最近一张图转视频",
        feature="video_generation",
        prompt="slow cinematic camera move, subtle breathing motion, rain particles drifting",
        model="grok-imagine-1.0-video",
        web_enabled=False,
        mode="video",
        tags=("safe", "video"),
    ),
]
