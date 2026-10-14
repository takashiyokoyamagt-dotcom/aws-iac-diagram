## NOTE: This is the minimum mandatory test
# run at least one test using the ./examples directory as your module source
# create additional *.tftest.hcl for your own unit / integration tests
# use tests/*.auto.tfvars to add non-default variables

run "agent_only_plan" {
  command = plan
  module {
    source = "./examples/agent-only"
  }
}

run "agent_only_apply" {
  command = apply
  module {
    source = "./examples/agent-only"
  }
}
