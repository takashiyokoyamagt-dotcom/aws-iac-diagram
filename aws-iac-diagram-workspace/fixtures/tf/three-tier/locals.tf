locals {
  name = var.project

  # CloudFormation 版の Mappings: EnvConfig に対応する
  env_config = {
    dev = {
      db_instance_class = "db.t4g.micro"
      app_desired_count = 1
      db_multi_az       = false
      enable_bastion    = false
    }
    prod = {
      db_instance_class = "db.m7g.large"
      app_desired_count = 3
      db_multi_az       = true
      enable_bastion    = true
    }
  }

  env = local.env_config[var.environment]
}
