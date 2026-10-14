run "kb_plan" {
  command = plan
  module {
    source = "./examples/knowledge-base-only"
  }
}

run "kb_apply" {
  command = apply
  module {
    source = "./examples/knowledge-base-only"
  }
}
