variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "demo"
}

variable "azs" {
  type    = list(string)
  default = ["ap-northeast-1a", "ap-northeast-1c"]
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "public_subnets" {
  type    = list(string)
  default = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "private_subnets" {
  type    = list(string)
  default = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "database_subnets" {
  type    = list(string)
  default = ["10.0.20.0/24", "10.0.21.0/24"]
}

# nginx-unprivileged は 8080 番で待ち受け、/ に 200 を返す（app_port と TG のヘルスチェックに合わせる）
variable "app_image" {
  type    = string
  default = "public.ecr.aws/nginx/nginx-unprivileged:1.27"
}

variable "app_port" {
  type    = number
  default = 8080
}
