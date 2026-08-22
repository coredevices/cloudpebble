# Auto-deploy pipeline test

Non-functional marker file. Touched to exercise the push-to-deploy pipeline
(build-cluster-images.yml → SHA-tagged image → commit to pebble-cluster → Flux
rollout with health gate). Safe to delete.

- 2026-08-22: first end-to-end qemu auto-deploy proof.
