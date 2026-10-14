run "app_inference_profile_plan" {
  command = plan
  module {
    source = "./examples/application-inference-profile"
  }
}

run "app_inference_profile_apply" {
  command = apply
  module {
    source = "./examples/application-inference-profile"
  }
}
