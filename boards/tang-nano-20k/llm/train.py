"""Trains the toy character language model of boards/tang-nano-20k/llm and writes it as integers for llm_gen.cho.

Python is the trainer only (numpy, manual gradients); inference is cancho on the host with the matrix-vector products on the FPGA.

Model: context of 4 characters, each an 8-number embedding (concatenated: 32), then three bias-free 32 x 32 layers: relu, relu, logits.
Parameters: V*8 + 3*1024 (V = vocabulary, at most 32). Greedy decoding. Integer pipeline after training: weights and embeddings rounded to
8 bits; after each of the first two layers the 32-bit sums are relu'd and rescaled to 0..127 by x = min(127, (a * M) >> 16).
Output: one text line per item, all integers (see llm_gen.cho for the order).
Usage: python3 train.py corpus.txt > model.txt
"""
import sys
import numpy as np

text = open(sys.argv[1]).read().strip().replace("\n", " ")
chars = sorted(set(text))
V = len(chars)
assert V <= 32, V
idx = {c: i for i, c in enumerate(chars)}
data = np.array([idx[c] for c in text])
CTX, ED = 4, 8
X = np.stack([data[i:i + CTX] for i in range(len(data) - CTX)])
Y = data[CTX:]
rng = np.random.default_rng(1)
E = rng.normal(0, 0.5, (V, ED))
W1 = rng.normal(0, 0.3, (32, 32)); W2 = rng.normal(0, 0.3, (32, 32)); W3 = rng.normal(0, 0.3, (V, 32))

def forward(Xb, E, W1, W2, W3):
    x0 = E[Xb].reshape(len(Xb), 32)
    a1 = np.maximum(0, x0 @ W1.T); a2 = np.maximum(0, a1 @ W2.T)
    return x0, a1, a2, a2 @ W3.T

params = [E, W1, W2, W3]
m = [np.zeros_like(p) for p in params]; v = [np.zeros_like(p) for p in params]
for step in range(1, 6001):
    x0, a1, a2, lg = forward(X, *params)
    lg -= lg.max(1, keepdims=True)
    p = np.exp(lg); p /= p.sum(1, keepdims=True)
    loss = -np.log(p[np.arange(len(Y)), Y]).mean()
    d = p; d[np.arange(len(Y)), Y] -= 1; d /= len(Y)
    gW3 = d.T @ a2; da2 = d @ params[3]
    da2 *= (a2 > 0); gW2 = da2.T @ a1; da1 = da2 @ params[2]
    da1 *= (a1 > 0); gW1 = da1.T @ x0; dx0 = da1 @ params[1]
    gE = np.zeros_like(params[0])
    np.add.at(gE, X.reshape(-1), dx0.reshape(-1, ED))
    for k, g in enumerate([gE, gW1, gW2, gW3]):
        m[k] = 0.9 * m[k] + 0.1 * g; v[k] = 0.999 * v[k] + 0.001 * g * g
        params[k] -= 0.01 * (m[k] / (1 - 0.9 ** step)) / (np.sqrt(v[k] / (1 - 0.999 ** step)) + 1e-8)
    if step % 1500 == 0:
        print(f"step {step} loss {loss:.4f}", file=sys.stderr)
E, W1, W2, W3 = params

def q(a):
    s = 127 / np.abs(a).max()
    return np.round(a * s).astype(np.int64), s
Eq, sE = q(E); W1q, s1 = q(W1); W2q, s2 = q(W2); W3q, s3 = q(W3)
W3p = np.zeros((32, 32), dtype=np.int64); W3p[:V] = W3q
# calibration: the largest activation sums over every training context, in the integer pipeline
x0 = Eq[X].reshape(len(X), 32)
y1 = x0 @ W1q.T; a1 = np.maximum(0, y1); M1 = int(round(127 * 65536 / a1.max()))
x1 = np.minimum(127, (a1 * M1) >> 16)
y2 = x1 @ W2q.T; a2 = np.maximum(0, y2); M2 = int(round(127 * 65536 / a2.max()))
x2 = np.minimum(127, (a2 * M2) >> 16)

def float_next(ctx):
    _, _, _, lg = forward(np.array([ctx]), E, W1, W2, W3); return int(lg[0].argmax())
def int_next(ctx):
    a = Eq[ctx].reshape(32)
    b = np.minimum(127, (np.maximum(0, W1q @ a) * M1) >> 16)
    c = np.minimum(127, (np.maximum(0, W2q @ b) * M2) >> 16)
    return int((W3p @ c)[:V].argmax())
prompt = [idx[c] for c in text[:CTX]]
def gen(f, n=80):
    out = list(prompt)
    for _ in range(n): out.append(f(out[-CTX:]))
    return out
fo, io = gen(float_next), gen(int_next)
acc_f = np.mean([float_next(list(x)) == y for x, y in zip(X, Y)]); acc_i = np.mean([int_next(list(x)) == y for x, y in zip(X, Y)])
print(f"next-character accuracy on the training text: float {acc_f:.3f}, integer pipeline {acc_i:.3f}", file=sys.stderr)
print("float greedy:   ", "".join(chars[i] for i in fo), file=sys.stderr)
print("integer greedy: ", "".join(chars[i] for i in io), file=sys.stderr)
out = lambda tag, a: print(tag, *[int(v) for v in np.array(a).reshape(-1)])
out("V", [V]); out("C", [ord(c) for c in chars]); out("P", prompt)
out("E", Eq.reshape(-1)); out("A", W1q); out("B", W2q); out("D", W3p)
out("M", [M1, M2]); out("F", fo[CTX:])
