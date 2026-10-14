run "agent_collaborator_plan" {
  command = plan
  module {
    source = "./examples/agent-collaborator"
  }
}

run "agent_collaborator_apply" {
  command = apply
  module {
    source = "./examples/agent-collaborator"
  }
}
