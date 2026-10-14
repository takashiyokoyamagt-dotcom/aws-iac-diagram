run "bda_plan" {
  command = plan
  module {
    source = "./examples/bda"
  }
}

run "bda_apply" {
  command = apply
  module {
    source = "./examples/bda"
  }
}
