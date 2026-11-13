import sys
sys.path.insert(0, '.')
from expert_pack.builtin.demo import run_demo

for count in (5, 8, 12):
    rates = []
    for seed in range(1, 11):
        r = run_demo(count=count, seed=seed)
        rates.append((r.baseline_rate, r.memory_rate))
    b = sum(x for x, _ in rates) / len(rates)
    m = sum(y for _, y in rates) / len(rates)
    per_seed = ["%.2f" % y for _, y in rates]
    print("count=%d baseline=%.2f memory=%.2f per-seed=%s" % (count, b, m, per_seed))
