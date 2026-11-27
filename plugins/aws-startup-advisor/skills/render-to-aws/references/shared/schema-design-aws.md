# Render AWS design contract

`aws-design.json` validates against `schema-render-aws-design.json`. The inventory and preferences fingerprints bind the exact raw inputs. Mappings are byte-sorted by source resource ID and form a one-to-one accounting partition of inventory resources.

Every mapping has one concrete `aws_service`. Its decision records a closed `candidate_set`; the selected service occurs once in that set, and every other member occurs once in `rejected_candidates`. Ordered collections use contiguous ordinals starting at one. Reasons must identify a fired rule, eliminator, evidence fact, or explicit default rather than saying only “not selected.”

`aws_config` sizes (`vcpu`/`memory_gb`/`desired_count`, `instance_class`, `node_type`) are the right-sized Balanced design: the sizes Estimate prices as Balanced and the generated Terraform implements. Every sized mapping records `aws_config.sizing_provenance` ∈ {`table`, `measured`, `user_stated`, `model_prior`}; `measured` means the metrics window passed every threshold in `knowledge/estimate/rightsizing-thresholds.json`, and `table` means the captured plan stands, so Balanced equals like-for-like for that line.
Topology resources are `consumed_topology` but still name their concrete AWS boundary, configuration, history, or promotion target. A completed design has no unresolved/deferred infrastructure row. The sole approved deferral is the exact `deferred_shared_ai_engine` object; it cannot carry targets, models, pricing, adapters, or Terraform.
