"""FastAPI service that exposes Prefill attack experiments for Lab 1."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List, Literal

import torch
from fastapi import FastAPI
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_NAME = os.environ.get("PREFILL_MODEL_NAME", "Qwen/Qwen3-8B-FP8")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


class PrefillRequest(BaseModel):
    user_prompt: str = Field(..., description="참여자가 전달한 최종 User 프롬프트")
    guardrail: str = Field(
        "",
        description="시스템이 항상 넣는 정책/보안 지침. baseline과 attack 모두에 포함됩니다.",
    )
    prefill: str = Field(
        "",
        description="공격자가 삽입하는 Prefill 문구. baseline에는 포함되지 않습니다.",
    )
    max_new_tokens: int = Field(128, ge=16, le=512)
    temperature: float = Field(0.8, ge=0.1, le=2.0)
    top_k: int = Field(5, ge=1, le=20)
    seed: int | None = Field(
        default=None, description="재현 가능한 비교가 필요할 때 고정할 난수 시드"
    )


class PrefillResponse(BaseModel):
    model_name: str
    device: Literal["cuda", "cpu"]
    baseline: Dict[str, object]
    attack: Dict[str, object]


@lru_cache(maxsize=1)
def load_model():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True,
        torch_dtype="auto"
    )
    model.to(DEVICE)
    model.eval()
    return tokenizer, model


def build_chat_prompt(tokenizer, guardrail: str, user_prompt: str) -> str:
    """Use the tokenizer's chat template so formatting matches the base model."""
    messages: List[Dict[str, str]] = []
    if guardrail:
        messages.append({"role": "system", "content": guardrail.strip()})
    messages.append(
        {
            "role": "user",
            "content": user_prompt.strip() if user_prompt else "",
        }
    )
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def inject_into_assistant(prompt: str, prefill: str) -> str:
    """Attach attacker-provided text directly to the assistant turn."""
    cleaned = prefill.strip()
    if not cleaned:
        return prompt
    suffix = cleaned if cleaned.endswith("\n") else cleaned + "\n"
    return prompt + suffix


def run_generation(
    tokenizer,
    model,
    prompt: str,
    *,
    max_new_tokens: int,
    temperature: float,
    top_k: int,
    seed: int | None,
) -> Dict[str, object]:
    inputs = tokenizer(prompt, return_tensors="pt").to(DEVICE)
    if seed is not None:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    with torch.inference_mode():
        logits = model(**inputs).logits[:, -1, :]
        probs = torch.softmax(logits / temperature, dim=-1)
        topk = torch.topk(probs, k=top_k)
        generated = model.generate(
            **inputs,
            do_sample=True,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            pad_token_id=tokenizer.eos_token_id,
        )
    decoded = tokenizer.decode(
        generated[0][inputs.input_ids.shape[-1] :], skip_special_tokens=True
    )
    topk_tokens = [
        {"token": tokenizer.decode([idx]), "prob": float(prob)}
        for idx, prob in zip(topk.indices[0], topk.values[0])
    ]
    return {
        "prompt": prompt,
        "tokens_in_prompt": int(inputs.input_ids.shape[-1]),
        "topk_next_token": topk_tokens,
        "generated_text": decoded.strip(),
    }


app = FastAPI(
    title="Lab1 Prefill Attack Service",
    description="Baseline vs Prefill attack 비교를 위한 경량 API",
    version="0.1.0",
)


@app.on_event("startup")
async def warm_model_cache():
    """Ensure tokenizer/model weights load before the first request arrives."""
    load_model()


@app.post("/prefill/run", response_model=PrefillResponse)
def run_prefill(request: PrefillRequest):
    tokenizer, model = load_model()
    prompt_baseline = build_chat_prompt(tokenizer, request.guardrail, request.user_prompt)
    prompt_attack = inject_into_assistant(prompt_baseline, request.prefill)
    baseline = run_generation(
        tokenizer,
        model,
        prompt_baseline,
        max_new_tokens=request.max_new_tokens,
        temperature=request.temperature,
        top_k=request.top_k,
        seed=request.seed,
    )
    attack = run_generation(
        tokenizer,
        model,
        prompt_attack,
        max_new_tokens=request.max_new_tokens,
        temperature=request.temperature,
        top_k=request.top_k,
        seed=request.seed,
    )
    return PrefillResponse(
        model_name=MODEL_NAME,
        device=DEVICE,
        baseline=baseline,
        attack=attack,
    )


@app.get("/healthz")
def healthcheck():
    return {"status": "ok", "model": MODEL_NAME, "device": DEVICE}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("prefill_server:app", host="0.0.0.0", port=8000, reload=False)
