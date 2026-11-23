---
license_name: nvidia-open-model-license
license_link: >-
  https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/
base_model:
- nvidia/Mistral-NeMo-12B-Base
library_name: transformers
---

# Riva-Translate-4B-Instruct-v2

## Model Overview
The Riva-Translate-4B-Instruct-v2 Neural Machine Translation model translates text in English and 36 non-English languages. The supported languages are: English(en), Czech(cs), Danish(da), German(de), Greek(el), European Spanish(es-ES), LATAM Spanish(es-US), Finnish(fi), French(fr), Hungarian(hu), Italian(it), Lithuanian(lt), Latvian(lv), Dutch(nl), Norwegian(no), Polish(pl), European Portuguese(pt-PT), Brazilian Portuguese(pt-BR), Romanian(ro), Russian(ru), Slovak(sk), Swedish(sv), Simplified Chinese(zh-CN), Traditional Chinese(zh-TW), Japanese(ja), Hindi(hi), Korean(ko), Estonian(et), Slovenian(sl), Bulgarian(bg), Ukrainian(uk), Croatian(hr), Arabic(ar), Vietnamese(vi), Turkish(tr), Indonesian(id), Thai(th). It supports both sentence- and document-level translation. The model surpasses all in-house NMT models we've built so far. <br>

**Model Developer:** NVIDIA 

**Model Dates:** Riva-Translate-4B-Instruct-v2 was trained between Nov 2025 and May 2026.

## License
GOVERNING TERMS: Use of the model is governed by the [NVIDIA Open Model License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/) ADDITIONAL INFORMATION: [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0).

## Quick Start Guide

### How to Choose the Language Pair

To select a language pair for translation, include one of the following tags in the system prompt:
* `en-zh-cn` or `en-zh`: English to Simplified Chinese
* `en-zh-tw`: English to Traditional Chinese
* `en-ar`: English to Arabic
* `en-bg`: English to Bulgarian
* `en-cs`: English to Czech
* `en-da`: English to Danish
* `en-de`: English to German
* `en-el`: English to Greek
* `en-es` or `en-es-es`: English to European Spanish
* `en-es-us`: English to Latin American Spanish
* `en-et`: English to Estonian
* `en-fi`: English to Finnish
* `en-fr`: English to French
* `en-hi`: English to Hindi
* `en-hr`: English to Croatian
* `en-hu`: English to Hungarian
* `en-id`: English to Indonesian
* `en-it`: English to Italian
* `en-ja`: English to Japanese
* `en-ko`: English to Korean
* `en-lt`: English to Lithuanian
* `en-lv`: English to Latvian
* `en-nl`: English to Dutch
* `en-no`: English to Norwegian
* `en-pl`: English to Polish
* `en-pt` or `en-pt-pt`: English to European Portuguese
* `en-pt-br`: English to Brazilian Portuguese
* `en-ro`: English to Romanian
* `en-ru`: English to Russian
* `en-sk`: English to Slovak
* `en-sl`: English to Slovenian
* `en-sv`: English to Swedish
* `en-th`: English to Thai
* `en-tr`: English to Turkish
* `en-uk`: English to Ukrainian
* `en-vi`: English to Vietnamese
* `zh-en` or `zh-cn-en`: Simplified Chinese to English
* `zh-tw-en`: Traditional Chinese to English
* `ar-en`: Arabic to English
* `bg-en`: Bulgarian to English
* `cs-en`: Czech to English
* `da-en`: Danish to English
* `de-en`: German to English
* `el-en`: Greek to English
* `es-en` or `es-es-en`: European Spanish to English
* `es-us-en`: Latin American Spanish to English
* `et-en`: Estonian to English
* `fi-en`: Finnish to English
* `fr-en`: French to English
* `hi-en`: Hindi to English
* `hr-en`: Croatian to English
* `hu-en`: Hungarian to English
* `id-en`: Indonesian to English
* `it-en`: Italian to English
* `ja-en`: Japanese to English
* `ko-en`: Korean to English
* `lt-en`: Lithuanian to English
* `lv-en`: Latvian to English
* `nl-en`: Dutch to English
* `no-en`: Norwegian to English
* `pl-en`: Polish to English
* `pt-en` or `pt-pt-en`: European Portuguese to English
* `pt-br-en`: Brazilian Portuguese to English
* `ro-en`: Romanian to English
* `ru-en`: Russian to English
* `sk-en`: Slovak to English
* `sl-en`: Slovenian to English
* `sv-en`: Swedish to English
* `th-en`: Thai to English
* `tr-en`: Turkish to English
* `uk-en`: Ukrainian to English
* `vi-en`: Vietnamese to English


### Use it with Transformers

```
from transformers import AutoTokenizer, AutoModelForCausalLM


tokenizer = AutoTokenizer.from_pretrained("nvidia/Riva-Translate-4B-Instruct-v2")
model = AutoModelForCausalLM.from_pretrained("nvidia/Riva-Translate-4B-Instruct-v2")

messages = [
    {
        "role": "system",
        "content": "en-zh-cn",
    },
    {"role": "user", "content": "The GRACE mission is a collaboration between the NASA and German Aerospace Center.?"},
 ]
tokenized_chat = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(model.device)
outputs = model.generate(tokenized_chat,  max_new_tokens=128, pad_token_id=tokenizer.eos_token_id)
print(tokenizer.decode(outputs[0]))
```


### Use it with vLLM
To install vllm, use the following pip command in a terminal within a supported environment.

```
pip install vllm: 0.19.1
```

Launch a vLLM server using the below python command. In this example, we use a context length of 8k as supported by the model.

```
FLASHINFER_DISABLE_VERSION_CHECK=1 python3 -m vllm.entrypoints.openai.api_server \
    --model nvidia/Riva-Translate-4B-Instruct-v2 \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 8192 \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --served-model-name Riva-Translate-4B-Instruct-v2
```

Alternatively, you can use Docker to launch a vLLM server.

```
docker run --runtime nvidia --gpus all \
           -v ~/.cache/huggingface:/root/.cache/huggingface \
           -p 8000:8000 \
           --ipc=host \
           vllm/vllm-openai:v0.5.3.post1 \
           --model nvidia/Riva-Translate-4B-Instruct-v2 \
           --dtype bfloat16 \
           --gpu-memory-utilization 0.95 \
           --max-model-len 8192 \
           --host 0.0.0.0 \
           --port 8000 \
           --tensor-parallel-size 1 \
           --served-model-name Riva-Translate-4B-Instruct-v2


```

If you are using DGX Spark or Jetson Thor, please use [this vllm container](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/vllm?version=25.12.post1-py3). On Jetson Thor, be sure to include `--runtime nvidia` when running the Docker container.

```
# On DGX SPark or Jetson Thor
docker run \
  --runtime nvidia \ # Remove this on DGX Spark
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -p 8000:8000 \
  --ipc=host \
  nvcr.io/nvidia/vllm:25.12.post1-py3 \
  vllm serve nvidia/Riva-Translate-4B-Instruct-v2 \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 8192 \
    --host 0.0.0.0 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --served-model-name Riva-Translate-4B-Instruct-v2


```

On Jetson Thor, the previous vLLM cache is not currently cleaned automatically, so it must be cleared manually. Always run this command on the host before serving any model on Jetson Thor.

```
sudo sysctl -w vm.drop_caches=3
```

Here is an example client code for vLLM. 

```
curl http://localhost:8000/v1/chat/completions \
-H "Content-Type: application/json"
-d '{
"model": "Riva-Translate-4B-Instruct-v2",
"messages": [
      {"role": "system", "content": "en-zh"},
      {"role": "user", "content": "The GRACE mission is a collaboration between the NASA and German Aerospace Center.?"}
    ]
}'
```
### Chat Template Structure
```
{%- set language_pairs = {
  'en-zh-cn': {'source': 'English', 'target': 'Simplified Chinese'},
  'en-zh': {'source': 'English', 'target': 'Simplified Chinese'},
  'en-zh-tw': {'source': 'English', 'target': 'Traditional Chinese'},
  'en-ar': {'source': 'English', 'target': 'Arabic'},
  'en-de': {'source': 'English', 'target': 'German'},
  'en-es': {'source': 'English', 'target': 'European Spanish'},
  'en-es-es': {'source': 'English', 'target': 'European Spanish'},
  'en-es-us': {'source': 'English', 'target': 'Latin American Spanish'},
  'en-fr': {'source': 'English', 'target': 'French'},
  'en-ja': {'source': 'English', 'target': 'Japanese'},
  'en-ko': {'source': 'English', 'target': 'Korean'},
  'en-ru': {'source': 'English', 'target': 'Russian'},
  'en-pt': {'source': 'English', 'target': 'Brazilian Portuguese'},
  'en-pt-br': {'source': 'English', 'target': 'Brazilian Portuguese'},
  'en-pt-pt': {'source': 'English', 'target': 'European Portuguese'},
  'zh-en': {'source': 'Simplified Chinese', 'target': 'English'},
  'zh-cn-en': {'source': 'Simplified Chinese', 'target': 'English'},
  'zh-tw-en': {'source': 'Traditional Chinese', 'target': 'English'},
  'ar-en': {'source': 'Arabic', 'target': 'English'},
  'de-en': {'source': 'German', 'target': 'English'},
  'es-en': {'source': 'European Spanish', 'target': 'English'},
  'es-es-en': {'source': 'European Spanish', 'target': 'English'},
  'es-us-en': {'source': 'Latin American Spanish', 'target': 'English'},
  'fr-en': {'source': 'French', 'target': 'English'},
  'ja-en': {'source': 'Japanese', 'target': 'English'},
  'ko-en': {'source': 'Korean', 'target': 'English'},
  'ru-en': {'source': 'Russian', 'target': 'English'},
  'pt-en': {'source': 'Brazilian Portuguese', 'target': 'English'},
  'pt-br-en': {'source': 'Brazilian Portuguese', 'target': 'English'},
  'en-it': {'source': 'English', 'target': 'Italian'},
  'it-en': {'source': 'Italian', 'target': 'English'},
  'en-nl': {'source': 'English', 'target': 'Dutch'},
  'nl-en': {'source': 'Dutch', 'target': 'English'},
  'en-pl': {'source': 'English', 'target': 'Polish'},
  'pl-en': {'source': 'Polish', 'target': 'English'},
  'en-cs': {'source': 'English', 'target': 'Czech'},
  'cs-en': {'source': 'Czech', 'target': 'English'},
  'en-sv': {'source': 'English', 'target': 'Swedish'},
  'sv-en': {'source': 'Swedish', 'target': 'English'},
  'en-da': {'source': 'English', 'target': 'Danish'},
  'da-en': {'source': 'Danish', 'target': 'English'},
  'en-fi': {'source': 'English', 'target': 'Finnish'},
  'fi-en': {'source': 'Finnish', 'target': 'English'},
  'en-no': {'source': 'English', 'target': 'Norwegian'},
  'no-en': {'source': 'Norwegian', 'target': 'English'},
  'en-hu': {'source': 'English', 'target': 'Hungarian'},
  'hu-en': {'source': 'Hungarian', 'target': 'English'},
  'en-ro': {'source': 'English', 'target': 'Romanian'},
  'ro-en': {'source': 'Romanian', 'target': 'English'},
  'en-bg': {'source': 'English', 'target': 'Bulgarian'},
  'bg-en': {'source': 'Bulgarian', 'target': 'English'},
  'en-uk': {'source': 'English', 'target': 'Ukrainian'},
  'uk-en': {'source': 'Ukrainian', 'target': 'English'},
  'en-sk': {'source': 'English', 'target': 'Slovak'},
  'sk-en': {'source': 'Slovak', 'target': 'English'},
  'en-hr': {'source': 'English', 'target': 'Croatian'},
  'hr-en': {'source': 'Croatian', 'target': 'English'},
  'en-sl': {'source': 'English', 'target': 'Slovenian'},
  'sl-en': {'source': 'Slovenian', 'target': 'English'},
  'en-et': {'source': 'English', 'target': 'Estonian'},
  'et-en': {'source': 'Estonian', 'target': 'English'},
  'en-lv': {'source': 'English', 'target': 'Latvian'},
  'lv-en': {'source': 'Latvian', 'target': 'English'},
  'en-lt': {'source': 'English', 'target': 'Lithuanian'},
  'lt-en': {'source': 'Lithuanian', 'target': 'English'},
  'en-el': {'source': 'English', 'target': 'Greek'},
  'el-en': {'source': 'Greek', 'target': 'English'},
  'en-tr': {'source': 'English', 'target': 'Turkish'},
  'tr-en': {'source': 'Turkish', 'target': 'English'},
  'en-id': {'source': 'English', 'target': 'Indonesian'},
  'id-en': {'source': 'Indonesian', 'target': 'English'},
  'en-vi': {'source': 'English', 'target': 'Vietnamese'},
  'vi-en': {'source': 'Vietnamese', 'target': 'English'},
  'en-th': {'source': 'English', 'target': 'Thai'},
  'th-en': {'source': 'Thai', 'target': 'English'},
  'en-hi': {'source': 'English', 'target': 'Hindi'},
  'hi-en': {'source': 'Hindi', 'target': 'English'} 
} -%}

{%- set system_message = '' -%}
{%- set source_lang = '' -%}
{%- set target_lang = '' -%}

{%- if messages[0]['role'] == 'system' -%}
  {%- set lang_pair = messages[0]['content'] | trim -%}
  {%- set messages = messages[1:] -%}
  {%- if lang_pair in language_pairs -%}
    {%- set source_lang = language_pairs[lang_pair]['source'] -%}
    {%- set target_lang = language_pairs[lang_pair]['target'] -%}
    {%- set system_message = 'You are an expert at translating text from ' + source_lang + ' to ' + target_lang + '.' -%}
  {%- else -%}
    {%- set system_message = 'You are a translation expert.' -%}
  {%- endif -%}
{%- endif -%}

{{- '<s>System\n' + system_message + '</s>\n' -}}

{%- for message in messages -%}
  {%- if (message['role'] in ['user']) != (loop.index0 % 2 == 0) -%}
    {{- raise_exception('Conversation roles must alternate between user and assistant') -}}
  {%- elif message['role'] == 'user' -%}
    {%- set user_content = (
          target_lang
          and 'What is the ' + target_lang + ' translation of the sentence: ' + message['content'] | trim
          or message['content'] | trim
        ) -%}
    {{- '<s>User\n' + user_content + '</s>\n' -}}
  {%- elif message['role'] == 'assistant' -%}
    {{- '<s>Assistant\n' + message['content'] | trim + '</s>\n' -}}
  {%- endif -%}
{%- endfor -%}

{%- if add_generation_prompt -%}
  {{ '<s>Assistant\n' }}
{%- endif -%}
```


## Evaluation
### FLORES-101 — En→Any

| Target Language | sacreBLEU | COMET-DA | XCOMET-XXL |
|---|--:|--:|--:|
| Czech | 28.30 | 0.89 | 0.90 |
| Danish | 42.00 | 0.82 | 0.95 |
| German | 37.10 | 0.67 | 0.97 |
| Greek | 22.10 | 0.71 | 0.84 |
| European Spanish | 28.90 | 0.76 | 0.96 |
| Latin America Spanish | 28.70 | 0.76 | 0.96 |
| Finnish | 18.20 | 0.89 | 0.82 |
| French | 48.70 | 0.83 | 0.94 |
| Hungarian | 20.20 | 0.86 | 0.90 |
| Italian | 27.90 | 0.75 | 0.93 |
| Lithuanian | 21.40 | 0.88 | 0.84 |
| Latvian | 24.80 | 0.83 | 0.80 |
| Dutch | 24.10 | 0.61 | 0.93 |
| Norwegian | 29.50 | 0.80 | 0.94 |
| Polish | 18.20 | 0.72 | 0.87 |
| European Portuguese | 44.00 | 0.88 | 0.96 |
| Brazilian Portuguese | 48.00 | 0.91 | 0.96 |
| Romanian | 36.50 | 0.88 | 0.91 |
| Russian | 29.60 | 0.74 | 0.92 |
| Slovak | 28.70 | 0.88 | 0.89 |
| Swedish | 39.60 | 0.85 | 0.94 |
| Simplified Chinese | 40.20 | 0.68 | 0.91 |
| Traditional Chinese | 34.80 | 0.67 | 0.91 |
| Japanese | 33.40 | 0.73 | 0.91 |
| Hindi | 24.60 | 0.73 | 0.77 |
| Korean | 29.30 | 0.73 | 0.91 |
| Estonian | 21.20 | 0.95 | 0.81 |
| Slovenian | 24.40 | 0.81 | 0.88 |
| Bulgarian | 35.60 | 0.82 | 0.91 |
| Ukrainian | 26.40 | 0.74 | 0.89 |
| Croatian | 24.10 | 0.81 | 0.87 |
| Arabic | 25.10 | 0.65 | 0.89 |
| Vietnamese | 37.10 | 0.70 | 0.89 |
| Turkish | 21.70 | 0.93 | 0.87 |
| Indonesian | 41.60 | 0.85 | 0.94 |
| Thai | 26.80 | 0.43 | 0.77 |
| **AVG** | **30.36** | **0.78** | **0.90** |

---

### FLORES-101 — Any→En

| Source Language | sacreBLEU | COMET-DA | XCOMET-XXL |
|---|---|---|---|
| Czech | 40.60 | 0.75 | 0.94 |
| Danish | 47.90 | 0.83 | 0.95 |
| German | 44.60 | 0.77 | 0.96 |
| Greek | 36.30 | 0.73 | 0.92 |
| European Spanish | 32.80 | 0.75 | 0.95 |
| Latin America Spanish | 32.80 | 0.75 | 0.95 |
| Finnish | 33.40 | 0.75 | 0.89 |
| French | 45.20 | 0.82 | 0.96 |
| Hungarian | 35.50 | 0.74 | 0.92 |
| Italian | 35.10 | 0.76 | 0.95 |
| Lithuanian | 33.70 | 0.64 | 0.88 |
| Latvian | 35.00 | 0.70 | 0.89 |
| Dutch | 32.50 | 0.70 | 0.94 |
| Norwegian | 43.40 | 0.80 | 0.94 |
| Polish | 31.10 | 0.67 | 0.93 |
| European Portuguese | 49.60 | 0.85 | 0.96 |
| Brazilian Portuguese | 49.60 | 0.85 | 0.96 |
| Romanian | 43.80 | 0.80 | 0.94 |
| Russian | 36.70 | 0.68 | 0.94 |
| Slovak | 39.10 | 0.73 | 0.93 |
| Swedish | 47.50 | 0.83 | 0.95 |
| Simplified Chinese | 30.00 | 0.72 | 0.96 |
| Traditional Chinese | 29.00 | 0.70 | 0.94 |
| Japanese | 28.00 | 0.69 | 0.93 |
| Hindi | 38.70 | 0.74 | 0.91 |
| Korean | 30.30 | 0.71 | 0.93 |
| Estonian | 36.40 | 0.74 | 0.87 |
| Slovenian | 34.90 | 0.69 | 0.91 |
| Bulgarian | 41.30 | 0.73 | 0.94 |
| Ukrainian | 40.00 | 0.70 | 0.93 |
| Croatian | 37.60 | 0.70 | 0.91 |
| Arabic | 40.70 | 0.72 | 0.92 |
| Vietnamese | 36.70 | 0.73 | 0.94 |
| Turkish | 37.00 | 0.75 | 0.91 |
| Indonesian | 43.60 | 0.81 | 0.95 |
| Thai | 29.00 | 0.66 | 0.90 |
| **AVG** | **37.76** | **0.74** | **0.93** |

---

### WMT24++ — En→Any

| Target Language | sacreBLEU | COMET-DA | XCOMET-XXL |
|---|--:|--:|--:|
| Czech | 21.80 | 0.61 | 0.73 |
| Danish | 36.70 | 0.58 | 0.85 |
| German | 27.50 | 0.45 | 0.90 |
| Greek | 28.90 | 0.57 | 0.71 |
| European Spanish | 41.70 | 0.65 | 0.87 |
| Latin America Spanish | 41.50 | 0.65 | 0.86 |
| Finnish | 21.20 | 0.73 | 0.73 |
| French | 34.80 | 0.53 | 0.81 |
| Hungarian | 18.10 | 0.59 | 0.76 |
| Italian | 32.70 | 0.59 | 0.82 |
| Lithuanian | 13.90 | 0.61 | 0.68 |
| Latvian | 20.00 | 0.54 | 0.62 |
| Dutch | 28.10 | 0.43 | 0.84 |
| Norwegian | 37.40 | 0.70 | 0.86 |
| Polish | 17.30 | 0.49 | 0.72 |
| European Portuguese | 33.00 | 0.59 | 0.85 |
| Brazilian Portuguese | 38.50 | 0.66 | 0.86 |
| Romanian | 31.60 | 0.63 | 0.78 |
| Russian | 20.70 | 0.42 | 0.79 |
| Slovak | 19.70 | 0.58 | 0.72 |
| Swedish | 35.90 | 0.64 | 0.85 |
| Simplified Chinese | 34.90 | 0.47 | 0.80 |
| Traditional Chinese | 32.50 | 0.54 | 0.82 |
| Japanese | 23.10 | 0.46 | 0.80 |
| Hindi | 12.20 | 0.39 | 0.61 |
| Korean | 26.50 | 0.54 | 0.81 |
| Estonian | 20.70 | 0.75 | 0.69 |
| Slovenian | 23.00 | 0.56 | 0.73 |
| Bulgarian | 29.10 | 0.59 | 0.76 |
| Ukrainian | 23.70 | 0.52 | 0.76 |
| Croatian | 21.20 | 0.52 | 0.72 |
| Arabic | 9.70 | 0.23 | 0.73 |
| Vietnamese | 31.40 | 0.40 | 0.77 |
| Turkish | 19.90 | 0.61 | 0.71 |
| Indonesian | 29.70 | 0.52 | 0.82 |
| Thai | 21.60 | 0.24 | 0.65 |
| **AVG** | **26.67** | **0.54** | **0.77** |


### WMT24++ — Any→En

| Source Language | sacreBLEU | COMET-DA | XCOMET-XXL |
|---|---|---|---|
| Czech | 34.40 | 0.56 | 0.84 |
| Danish | 39.70 | 0.66 | 0.89 |
| German | 33.40 | 0.59 | 0.90 |
| Greek | 40.40 | 0.63 | 0.83 |
| European Spanish | 43.10 | 0.67 | 0.90 |
| Latin America Spanish | 43.10 | 0.67 | 0.90 |
| Finnish | 32.70 | 0.62 | 0.81 |
| French | 36.30 | 0.62 | 0.88 |
| Hungarian | 28.80 | 0.55 | 0.82 |
| Italian | 39.70 | 0.63 | 0.87 |
| Lithuanian | 22.20 | 0.40 | 0.75 |
| Latvian | 30.00 | 0.51 | 0.76 |
| Dutch | 34.50 | 0.58 | 0.88 |
| Norwegian | 44.90 | 0.72 | 0.89 |
| Polish | 28.80 | 0.52 | 0.84 |
| European Portuguese | 36.00 | 0.64 | 0.88 |
| Brazilian Portuguese | 39.30 | 0.66 | 0.89 |
| Romanian | 40.10 | 0.62 | 0.83 |
| Russian | 27.20 | 0.40 | 0.84 |
| Slovak | 29.50 | 0.54 | 0.83 |
| Swedish | 42.10 | 0.70 | 0.89 |
| Simplified Chinese | 23.60 | 0.53 | 0.88 |
| Traditional Chinese | 29.50 | 0.61 | 0.90 |
| Japanese | 21.70 | 0.47 | 0.83 |
| Hindi | 20.90 | 0.54 | 0.84 |
| Korean | 26.00 | 0.55 | 0.84 |
| Estonian | 33.50 | 0.60 | 0.77 |
| Slovenian | 33.40 | 0.52 | 0.81 |
| Bulgarian | 36.70 | 0.60 | 0.84 |
| Ukrainian | 33.20 | 0.52 | 0.81 |
| Croatian | 33.60 | 0.51 | 0.80 |
| Arabic | 22.50 | 0.31 | 0.75 |
| Vietnamese | 29.50 | 0.50 | 0.86 |
| Turkish | 30.00 | 0.59 | 0.81 |
| Indonesian | 32.40 | 0.62 | 0.88 |
| Thai | 23.80 | 0.48 | 0.83 |
| **AVG** | **32.68** | **0.57** | **0.84** |


## Inference
* Engine: HF, vLLM  
* Test Hardware: NVIDIA A100, H100 80GB, Jetson Thor, DGX Spark

## Ethical Considerations

NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications. When downloaded or used in accordance with our terms of service, developers should work with their internal model team to ensure this model meets requirements for the relevant industry and use case and addresses unforeseen product misuse.

We advise against circumvention of any provided safety guardrails contained in the Model without a substantially similar guardrail appropriate for your use case. For more details: [Safety](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2/blob/main/safety.md) and [Explainability](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2/blob/main/explainability.md) Subcards.

For more detailed information on ethical considerations for this model, please see the Model Card++ [Bias](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2/blob/main/bias.md), and [Privacy](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2/blob/main/privacy.md) Subcards.

Please report model quality, risk, security vulnerabilities or NVIDIA AI Concerns [here](https://www.nvidia.com/en-us/support/submit-security-vulnerability/).


## Technical Limitations & Mitigation:
Accuracy varies based on the characteristics of input (Domain, Use Case, Noise, Context, etc.). Grammar errors and semantic issues may be present. As a potential mitigation, the user can change the prompt to get a better translation.