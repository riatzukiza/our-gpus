(pi-handoff
  (kind "eta-mu-kanban-migration")
  (batch "agent_shuv")
  (time "2026-05-29T04:03:19Z")
  (repo "/home/err/devel/orgs/shuv/our-gpus")
  (branch "master")
  (manifest "/tmp/eta-mu-kanban-batches/agent_shuv.json")
  (migrated-markdown 15)
  (verification "migration script plus eta-mu-beta kanban count for every board")
  (entries
    (entry (spec-dir "specs") (board-dir "kanban") (markdown-files 15) (validation-total 15)))
  (concurrency "path-scoped staging only; no destructive repo-wide cleanup; eta-mu paths untouched"))
