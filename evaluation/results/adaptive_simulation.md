# Simulation: adaptive vs evenly spread quizzes

**This is a simulation, not a study with real students.** It shows how PersonaAI's real allocation and scoring code behaves for a simulated student.

- 200 simulated students × 10 quizzes of 10 questions, per mode
- 20 topics, 5 genuinely weak (hidden mastery 25%–45%; others 70%–95%)
- Assumption: each question answered on a topic (with its explanation) closes 8% of the gap to full mastery of that topic

| Measure | Adaptive | Even mix |
|---|---|---|
| Questions on truly weak topics (sessions 4–10) | 55% | 25% |
| Truly weak topics flagged as weak at least once within 10 quizzes | 73% | 70% |
| Students whose weak topics were all flagged within 10 quizzes | 18% | 10% |
| Quizzes needed to flag all weak topics (mean, when flagged) | 6.4 | 8.5 |
| Mean mastery of weak topics after 10 quizzes (started ~35%) | 68% | 55% |

With an even mix, about 25% of questions hit the weak topics by chance (5 of 20 topics). In the first quizzes adaptive mode has no weak topics to target yet and favours untested topics; once topics have 3+ answers it shifts ~60% of each quiz onto the ones it has flagged.

Detection is noisy by design: a topic is judged after only 3 answers, so a weak topic (~40% per question) still scores 2/3 about a third of the time and is not flagged then; and as the student improves on a topic it can leave the weak range before it is flagged. Raising the minimum answers would make flags more reliable but slower.

![Weak-topic mastery per quiz](adaptive_simulation.png)
