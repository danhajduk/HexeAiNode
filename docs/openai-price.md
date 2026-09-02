# OpenAI Pricing Notes

Verified: 2026-09-02

## Cost/Benefit Text Model Defaults

For the node's OpenAI fallback path, prefer the current GPT-5.6 family when available:

| Model | Best node use | Input / 1M | Cached input / 1M | Output / 1M |
| --- | --- | ---: | ---: | ---: |
| gpt-5.6-luna | Default economical cloud fallback for general task chat, classification, and summaries | $0.20 | $0.02 | $1.20 |
| gpt-5.6-terra | Escalation model when the local LLM or Luna is unlikely to complete a more complex coding/reasoning task | $2.00 | $0.20 | $12.00 |
| gpt-5.6-sol | Highest-capability escalation; keep disabled by default unless the operator accepts the higher spend | $4.00 | $0.40 | $20.00 |

GPT-5.6 Luna is the default cost/benefit choice because OpenAI positions it for cost-sensitive, high-volume workloads. GPT-5.6 Terra is the practical quality escalation because OpenAI positions it as the balanced intelligence/cost model. GPT-5.6 Sol is available as the flagship option but costs materially more, so the node should not prefer it automatically.

## Node Task Defaults

The node reads OpenAI per-task defaults from `config/provider-task-model-preferences.json`.

| Task family | Default OpenAI model | Reason |
| --- | --- | --- |
| `task.classification`, `task.sentiment_analysis`, `task.information_extraction` | `gpt-5-nano` | Cheapest effective model for short structured classifier-style work, based on live replay cost checks. |
| `task.chat`, `task.summarization`, `task.structured_extraction`, `task.translation`, `task.code_explanation` | `gpt-5.6-luna` | Best default cost/benefit GPT-5.6 model for general cloud fallback. |
| `task.reasoning`, `task.workflow_reasoning`, `task.task_planning`, `task.code_generation`, `task.code_review`, `task.code_debugging` | `gpt-5.6-terra` | Quality escalation for harder reasoning/coding while avoiding Sol's higher default cost. |
| `task.image_generation` | `gpt-image-2` | Current image-generation default. |
| `task.moderation`, `task.policy_check` | `omni-moderation-2024-09-26` | Dedicated moderation/policy model. |

## Image Generation Pricing

This table records OpenAI image generation prices per generated image in USD. Prices vary by model, quality, and output size.

## Price Per Image

| Model | Quality | 1024x1024 | 1024x1536 | 1536x1024 |
| --- | --- | ---: | ---: | ---: |
| GPT Image 2 | Low | $0.006 | $0.005 | $0.005 |
| GPT Image 2 | Medium | $0.053 | $0.041 | $0.041 |
| GPT Image 2 | High | $0.211 | $0.165 | $0.165 |
| GPT Image 1.5 | Low | $0.009 | $0.013 | $0.013 |
| GPT Image 1.5 | Medium | $0.034 | $0.050 | $0.050 |
| GPT Image 1.5 | High | $0.133 | $0.200 | $0.200 |
| GPT Image 1 | Low | $0.011 | $0.016 | $0.016 |
| GPT Image 1 | Medium | $0.042 | $0.063 | $0.063 |
| GPT Image 1 | High | $0.167 | $0.250 | $0.250 |
| GPT Image 1 Mini | Low | $0.005 | $0.006 | $0.006 |
| GPT Image 1 Mini | Medium | $0.011 | $0.015 | $0.015 |
| GPT Image 1 Mini | High | $0.036 | $0.052 | $0.052 |

## Token Rates

OpenAI also lists image model token rates separately on the pricing page.

| Model | Modality | Input / 1M | Cached input / 1M | Output / 1M |
| --- | --- | ---: | ---: | ---: |
| gpt-image-2 | Image | $8.00 | $2.00 | $30.00 |
| gpt-image-2 | Text | $5.00 | $1.25 | - |
| gpt-image-1.5 | Image | $8.00 | $2.00 | $32.00 |
| gpt-image-1.5 | Text | $5.00 | $1.25 | $10.00 |
| gpt-image-1-mini | Image | $2.50 | $0.25 | $8.00 |
| gpt-image-1-mini | Text | $2.00 | $0.20 | - |

Sources:

- OpenAI pricing page: https://developers.openai.com/api/docs/pricing
- OpenAI models page: https://developers.openai.com/api/docs/models
- OpenAI model comparison page: https://developers.openai.com/api/docs/models/compare
- GPT Image 2 model page: https://developers.openai.com/api/docs/models/gpt-image-2
- GPT Image 1.5 model page: https://developers.openai.com/api/docs/models/gpt-image-1.5
- GPT Image 1 model page: https://developers.openai.com/api/docs/models/gpt-image-1
- GPT Image 1 Mini model page: https://developers.openai.com/api/docs/models/gpt-image-1-mini
