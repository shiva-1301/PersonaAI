# Evaluation: answer accuracy with vs without the student's notes

- Questions: 30 (from `evaluation/questions.csv`)
- Notes indexed for RAG: BIG_DATA_UNIT-III.pdf, BIG_DATA_UNIT-4.pdf
- Answer model: gemini / gemini-3.5-flash-lite; judge: gemini / gemini-3.5-flash-lite (blind, order randomised)
- Retrieval: embedding -> cross-encoder
- Manual overrides applied: 0

| Condition | Correct | Partial | Wrong | Accuracy | Score (partial = ½) |
|---|---|---|---|---|---|
| With notes (RAG) | 25 | 5 | 0 | 83% | 92% |
| Without notes | 30 | 0 | 0 | 100% | 100% |

RAG abstained ("not found in your notes") on 0 question(s); these count as wrong. When it did answer, 83% of its answers were correct.

![Results](chart.png)

## Per unit

| Unit | Questions | RAG accuracy | No-RAG accuracy |
|---|---|---|---|
| III | 15 | 93% | 100% |
| IV | 15 | 73% | 100% |

## Questions where the two conditions disagree

- Q39 *What is the JOIN operator in Pig?* — RAG: **partial**, no-RAG: **correct**. Answer 1 correctly identifies that JOIN combines multiple relations, but misses the key detail about using a common key and lacks an example.
- Q50 *What are relational operators in Hive?* — RAG: **partial**, no-RAG: **correct**. It correctly identifies that relational operators are used for comparing values and lists some examples, but it misses several operators mentioned in the reference answer such as LIKE, RLIKE, IN, BETWEEN, and IS NULL.
- Q53 *What are UDFs in Hive?* — RAG: **partial**, no-RAG: **correct**. It correctly identifies that UDFs stand for User-Defined Functions and add custom processing logic, but it misses mentioning UDAF and UDTF types.
- Q56 *What is Bucketing in Hive?* — RAG: **partial**, no-RAG: **correct**. It covers the definition, performance benefits, and mentions bucketing, but cuts off the example abruptly.
- Q57 *How can data be imported into Hive?* — RAG: **partial**, no-RAG: **correct**. It mentions external ingestion via Sqoop, but misses the fundamental HiveQL import mechanisms like LOAD DATA and INSERT INTO SELECT.
