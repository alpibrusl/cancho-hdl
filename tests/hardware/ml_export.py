"""Helper for boards/tang-nano-20k/host/ml_infer.cho: turns a linear model fitted by cancho-ml's `ml` into the integer text the cancho
program reads. Python is only plumbing here; every number comes from the `ml` binary.

  python3 tests/hardware/ml_export.py /path/to/ml train.csv test.csv TARGET > infer.txt

It fits `ml fit --model linear`, recovers the coefficients from the model by predicting on the zero row and on each unit row (a linear model's
prediction is b + w.x, so w_i = predict(e_i) - predict(0), b = predict(0)), and asks `ml predict` for the test rows. Output, all integers
(micro-units, so the cancho side parses no decimals): `W w0 ... w{d-1} b`, then one `R x0 ... x{d-1} prediction` line per test row.
"""
import csv, json, os, subprocess, sys, tempfile

ml, train, test, target = sys.argv[1:5]
with tempfile.TemporaryDirectory() as td:
    model = os.path.join(td, "m.ml")
    subprocess.run([ml, "fit", "--model", "linear", "--target", target, "--output", model, train], check=True, capture_output=True)
    cols = [c for c in next(csv.reader(open(train))) if c != target]
    d = len(cols)

    def predict(rows):
        path = os.path.join(td, "q.csv")
        with open(path, "w") as f:
            f.write(",".join(cols) + "\n")
            for r in rows:
                f.write(",".join(repr(v) for v in r) + "\n")
        out = subprocess.run([ml, "predict", "--model-file", model, path], check=True, capture_output=True, text=True).stdout
        return [float(r[0]) for r in json.loads(out.strip().splitlines()[-1])["data"]["rows"]]

    basis = [[0.0] * d] + [[1.0 if j == i else 0.0 for j in range(d)] for i in range(d)]
    p = predict(basis)
    b = p[0]
    w = [p[i + 1] - b for i in range(d)]
    rows = [[float(v) for v in r] for r in list(csv.reader(open(test)))[1:]]
    preds = predict(rows)
    micro = lambda v: str(round(v * 1_000_000))
    print("W " + " ".join(micro(v) for v in w) + " " + micro(b))
    for r, y in zip(rows, preds):
        print("R " + " ".join(micro(v) for v in r) + " " + micro(y))
