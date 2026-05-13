# RouteGuard-Med evaluation report

Benchmark: `routeguard_med/benchmarks/routeguard_med_300.csv`
Corpus: `routeguard_med/data/sample_evidence.jsonl`
Training examples: 210
Held-out evaluation examples: 90

## Leaderboard

| router                |   n |   accuracy |   unsupported_claim_rate |   citation_precision |   correct_abstain |   correct_clarify |   retrieval_usefulness |   cost_per_query |   avg_latency_ms |   net_utility |
|:----------------------|----:|-----------:|-------------------------:|---------------------:|------------------:|------------------:|-----------------------:|-----------------:|-----------------:|--------------:|
| learned_tfidf_logreg  |  90 |   1        |                        0 |                    1 |          1        |         1         |               1        |         0.177267 |         0.853698 |       3.25556 |
| heuristic             |  90 |   0.655556 |                        0 |                    1 |          0.6      |         0.266667  |               0.94     |         0.228944 |         0.320637 |       1.93333 |
| value_aligned_utility |  90 |   0.622222 |                        0 |                    1 |          0.533333 |         0.0666667 |               0.944444 |         0.260089 |         0.38923  |       1.77778 |

## Failure modes

| router                | failure_mode                   |   count |
|:----------------------|:-------------------------------|--------:|
| heuristic             |                                |      59 |
| heuristic             | wrong_action_expected_clarify  |      11 |
| heuristic             | wrong_action_expected_abstain  |       6 |
| heuristic             | wrong_action_expected_escalate |       6 |
| heuristic             | wrong_action_expected_answer   |       5 |
| heuristic             | wrong_action_expected_retrieve |       3 |
| learned_tfidf_logreg  |                                |      90 |
| value_aligned_utility |                                |      56 |
| value_aligned_utility | wrong_action_expected_clarify  |      14 |
| value_aligned_utility | wrong_action_expected_escalate |       8 |
| value_aligned_utility | wrong_action_expected_abstain  |       7 |
| value_aligned_utility | wrong_action_expected_answer   |       5 |
