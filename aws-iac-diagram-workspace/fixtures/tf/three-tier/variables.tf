variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "demo"
}

# 既定値なし。env/dev.tfvars か env/prod.tfvars で与える（A4: 環境が複数あるので最初に1回だけ確認する）
variable "environment" {
  type = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment は dev か prod。"
  }
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

variable "admin_cidr" {
  type    = string
  default = "203.0.113.0/24"
}
