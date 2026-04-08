# flow-applicator scripts package
"""
Flow-based job application automation.

Modules:
  paths          - Dynamic path resolution (repo root, workspace, flows, applications)
  flow_engine    - FlowGraph/FlowNode/FlowEdge dataclasses + FlowRegistry
  answer_engine  - Priority-based answer resolution (templates → role → profile → LLM)
  dedup_checker  - Duplicate application detection via _index.json
  status_tracker - Application result logging
  flow_builder   - Convert Playwright snapshots into flow JSON nodes
  orchestrator   - Main entry point tying all modules together
"""
