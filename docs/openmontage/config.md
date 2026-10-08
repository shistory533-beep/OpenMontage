# Factory Configuration

Single file: `factory_config.yaml`

Sections: pipeline, providers, retry, qa_policy, output, observability.

- `approval_mode: automatic` → normal runs fully automatic; manual gates preserved for debugging.
- `providers` ordered list; selection uses `factory/provider_abstraction.py`; first free eligible wins.
- `retry_classes` limits retries to TRANSIENT only.
- `qa_policy.gate_before_publish: true` → final.mp4 blocked until all checks pass.
