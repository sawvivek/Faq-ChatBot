# TrustFAQ evaluation report

Test set: 86 queries (64 answerable, 16 unknown/unrelated, 6 ambiguous). Knowledge base: 27 FAQs. Thresholds: answer>=0.45, clarify>=0.3. Dense embeddings: off.

## Headline metrics

| Metric | Value |
|---|---|
| top1 | 0.875 |
| top3 | 0.969 |
| mrr | 0.922 |
| answered_correct | 0.641 |
| clarified_with_correct_option | 0.141 |
| safe_success | 0.781 |
| answered_wrong | 0.031 |
| abstained_on_answerable | 0.328 |
| selective_accuracy | 0.911 |
| unknown_precision | 0.432 |
| unknown_recall | 1.000 |
| unknown_f1 | 0.604 |
| false_answer_rate_negatives | 0.000 |
| ambiguous_not_answered | 0.667 |
| latency p50 / p95 (ms) | 5.1 / 7.2 |

## By category

| Category | n | Success | Top-1 retrieval | Success means |
|---|---|---|---|---|
| exact | 6 | 1.00 | 1.00 | answered correctly |
| paraphrase | 20 | 0.50 | 0.85 | answered correctly |
| typos | 10 | 0.80 | 0.90 | answered correctly |
| short | 8 | 0.88 | 1.00 | answered correctly |
| long | 4 | 0.00 | 0.75 | answered correctly |
| ambiguous | 6 | 0.67 | - | correctly did not answer |
| unknown | 8 | 1.00 | - | correctly did not answer |
| unrelated | 8 | 1.00 | - | correctly did not answer |
| followup | 6 | 0.67 | 0.83 | answered correctly |
| multilingual | 10 | 0.60 | 0.80 | answered correctly |

## Calibration (confidence bin -> fraction of cases handled correctly)

| Confidence | n | Correct |
|---|---|---|
| 0.00-0.30 | 25 | 0.52 |
| 0.30-0.55 | 15 | 0.47 |
| 0.55-0.75 | 10 | 0.80 |
| 0.75-1.00 | 30 | 0.97 |

## Threshold sweep (answer threshold)

| Threshold | Answered correctly | Answered wrongly | False answers on unknown/unrelated | Abstained on answerable |
|---|---|---|---|---|
| 0.35 | 0.688 | 0.062 | 0.000 | 0.250 |
| 0.45 | 0.641 | 0.031 | 0.000 | 0.328 |
| 0.55 | 0.578 | 0.031 | 0.000 | 0.391 |
| 0.65 | 0.500 | 0.016 | 0.000 | 0.484 |
| 0.75 | 0.469 | 0.016 | 0.000 | 0.516 |

## Failures (for error analysis)

| Category | Query | Expected | Got (status, FAQ) | Conf |
|---|---|---|---|---|
| paraphrase | Can I stay in a college hostel and how do I request it? | How do I get a hostel room? | clarify, - | 0.37 |
| paraphrase | Where will my semester marks be published? | How can I check my exam results? | ambiguous, - | 0.33 |
| paraphrase | Is it possible to settle fees using UPI? | How can I pay my fees? | unknown, - | 0.16 |
| paraphrase | Who is eligible for a merit based fee waiver? | Are scholarships available? | clarify, - | 0.37 |
| paraphrase | What happens to my deposit if I leave the course early? | What is the fee refund policy? | unknown, - | 0.19 |
| paraphrase | What is the minimum percentage of classes I must attend? | What is the minimum attendance requirement? | clarify, - | 0.33 |
| paraphrase | Which wireless network should I join on campus? | How do I connect to campus Wi-Fi? | unknown, - | 0.28 |
| paraphrase | I can't sign in to the student portal, what now? | I forgot my student portal password. How do I reset it? | unknown, - | 0.19 |
| paraphrase | Who should I approach if someone is bullying me? | How do I report ragging or harassment? | unknown, - | 0.27 |
| paraphrase | Where do I ask for a letter proving that I study here? | How do I get a bonafide certificate? | unknown, - | 0.25 |
| typos | how much tuiton fee do i hav to pay | What is the fee structure? | clarify, - | 0.32 |
| typos | exam resutl kab ayega | How can I check my exam results? | clarify, - | 0.41 |
| short | hostel | How do I get a hostel room? | ambiguous, - | 0.73 |
| long | Hi, I just got my admission confirmed and I am planning to m | How do I get a hostel room? | unknown, - | 0.29 |
| long | My friend told me that I might not be allowed to write the e | What is the minimum attendance requirement? | unknown, - | 0.27 |
| long | I am in my final year and I want to know how the whole campu | What is the placement process? | unknown, - | 0.20 |
| long | I was wondering if there is any possibility of getting some  | Are scholarships available? | unknown, - | 0.24 |
| ambiguous | help | AMBIG | answered, How can I contact the administration office? | 0.72 |
| ambiguous | form | AMBIG | answered, How do I apply for admission? | 0.49 |
| followup | what about the deposit? | How much is the hostel fee? | answered, How can I pay my fees? | 0.83 |
| followup | and when are they published? | How can I check my exam results? | unknown, - | 0.16 |
| multilingual | हॉस्टल में रूम कैसे मिलेगा | How do I get a hostel room? | clarify, - | 0.39 |
| multilingual | library kab khulti hai | What are the library timings? | answered, Where can I eat on campus and what are the canteen timings? | 0.56 |
| multilingual | शिष्यवृत्ती कशी मिळेल | Are scholarships available? | unknown, - | 0.29 |
| multilingual | प्रवेश कसा घ्यावा | How do I apply for admission? | clarify, - | 0.41 |

> Limits: small hand-written test set from one author, one sample KB. Numbers show the pipeline behaves sensibly on this data, not that it will reach the same accuracy on another institute's FAQs. Re-run on your own KB before quoting figures.
