variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "example"
}

variable "azs" {
  type    = list(string)
  default = ["ap-northeast-1a", "ap-northeast-1c"]
}

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

variable "public_subnets" {
  type    = list(string)
  default = ["10.10.0.0/24", "10.10.1.0/24"]
}

variable "private_subnets" {
  type    = list(string)
  default = ["10.10.10.0/24", "10.10.11.0/24"]
}

# for_each で Interface 型の VPC エンドポイントを作る
variable "interface_endpoints" {
  type    = list(string)
  default = ["ec2messages", "ssm", "ssmmessages"]
}
