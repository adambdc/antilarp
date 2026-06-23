# What the firewall refuses (reproduced live)

These are not assertions in prose — they are the firewall doing its job. Run:

```
python3 examples/replay_demo.py
```

The first half folds `examples/sample-ledger.jsonl` through the real `validate()` and
prints the legitimate crossings (including the load-bearing one, which carries a
decorrelated critic-confirm). The second half attempts three forged writes against a
throwaway ledger; each is **refused** by the same validator that gates every real write.

### 1. You cannot bank "I exceeded my substrate"

A `substrate`-class limit (the configured `hard_class`) can never be recorded as
`crossed`. Its only honest terminal is `substrate-hard`.

```
REFUSED  substrate recorded as crossed
         -> firewall: ll-0001: a substrate-class limit can never be crossed (anti-LARP); use the hard terminal
```

### 2. You cannot quietly cross an identity-class limit

A limit in a `joint_required` domain (`identity`) cannot be auto-crossed. Without an
explicit human co-sign (`joint=True`) it is recorded `surfaced`, not `crossed`.

```
REFUSED  identity crossed without joint co-sign
         -> firewall: ll-0002: domain 'identity' is not auto-crossed; surface it, or cross with joint=True (a human co-sign)
```

### 3. A load-bearing crossing needs a decorrelated second mind

A consequential (`load_bearing`) crossing is refused unless a non-self, named critic
returns `verdict: confirm`. Proof alone is provably insufficient — a model cannot
reliably self-verify.

```
REFUSED  load-bearing crossing with no decorrelated critic
         -> ll-0003: a load-bearing crossing needs a DECORRELATED critic, not self — get a verdict from a second mind, then cross with --critic-by <a non-self, named second party> --critic-verdict confirm
```

The honest residual: the critic's `by` label is self-reported. A non-self-*looking*
forged label (`by="gpt"` with no real second model) is the author's to make, like a
hand-edit — the gate is a speed bump, not a cryptographic attestation. Everything that
can be enforced at the data layer is; that boundary is documented, not hidden.
