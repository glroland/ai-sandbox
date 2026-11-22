# Custom lm-evaluation-harness tasks

Task definitions the notebooks pass to `lm_eval --include_path`. They exist because the stock versions
of these benchmarks do not work against a chat endpoint:

| Folder | Why it is needed |
|---|---|
| `truthfulqa/` | The standard `truthfulqa_mc1` ranks answers by log-probability, which chat endpoints do not return. This asks the question as lettered multiple choice instead, shuffling the options (the dataset always lists the true answer first) and joining in each question's category. |
| `global_mmlu_lite/` | Global-MMLU Lite in 15 languages as lettered multiple choice, keeping the dataset's culturally-sensitive / culturally-agnostic labels. |
| `mgsm_chat/` | The stock `mgsm_native_cot` stops generating at the first line break, which cuts off a chat model's step-by-step answer. This version lets the model finish and reads the number after `Answer:`. |
